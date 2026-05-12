from contextlib import contextmanager
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, field_validator
from typing import Optional
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import re
import redis
import json
import jwt
import httpx
import random
import string
import secrets
import pika
from datetime import datetime

app = FastAPI(title="Registration Service", version="2.0.0")

Instrumentator().instrument(app).expose(app)

CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:8080,http://localhost:8081,http://localhost:8082",
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JWT_SECRET = os.getenv("JWT_SECRET", "event-mgmt-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY", "")
EVENT_SERVICE_URL = os.getenv("EVENT_SERVICE_URL", "http://event-service:8000")

security = HTTPBearer()

_db_pool = None
_redis_client = None
_http_client = None
_rabbitmq_channel = None

SUPPORTED_PAYMENT_METHODS = {"free", "card", "credit_card", "paypal", "bank_transfer"}

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS registrations (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    event_id INT NOT NULL,
    registration_date TIMESTAMP DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'confirmed',
    payment_method VARCHAR(50) DEFAULT 'free',
    payment_status VARCHAR(20) DEFAULT 'pending',
    payment_reference VARCHAR(100),
    payment_gateway VARCHAR(50),
    payment_processed_at TIMESTAMP,
    ticket_number VARCHAR(20) UNIQUE,
    notes TEXT,
    UNIQUE(user_id, event_id)
)
"""


def _get_pool():
    global _db_pool
    if _db_pool is None or _db_pool.closed:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            host=os.getenv("DB_HOST", "postgres"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "eventdb"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
        )
    return _db_pool


def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
    return _redis_client


def get_http_client():
    global _http_client
    if _http_client is None:
        _http_client = httpx.Client(timeout=10.0)
    return _http_client


def _get_rabbitmq_channel():
    global _rabbitmq_channel
    if _rabbitmq_channel is None:
        params = pika.ConnectionParameters(
            host=os.getenv("RABBITMQ_HOST", "rabbitmq"),
            port=int(os.getenv("RABBITMQ_PORT", "5672")),
            credentials=pika.PlainCredentials(
                os.getenv("RABBITMQ_USER", "guest"),
                os.getenv("RABBITMQ_PASSWORD", "guest"),
            ),
            heartbeat=600,
            blocked_connection_timeout=300,
        )
        conn = pika.BlockingConnection(params)
        _rabbitmq_channel = conn.channel()
        _rabbitmq_channel.exchange_declare(
            exchange="events", exchange_type="topic", durable=True
        )
    return _rabbitmq_channel


def publish_event(routing_key: str, payload: dict):
    try:
        ch = _get_rabbitmq_channel()
        ch.basic_publish(
            exchange="events",
            routing_key=routing_key,
            body=json.dumps(payload),
            properties=pika.BasicProperties(
                content_type="application/json", delivery_mode=2
            ),
        )
    except Exception:
        pass


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    return decode_token(credentials.credentials)


def require_role(*allowed_roles):
    def role_checker(user: dict = Depends(get_current_user)):
        if user.get("role") not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required: {list(allowed_roles)}, has: '{user.get('role')}'",
            )
        return user

    return role_checker


@contextmanager
def get_db():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.set_session(autocommit=False)
        yield conn
    finally:
        pool.putconn(conn)


class RegistrationCreate(BaseModel):
    event_id: int
    payment_method: Optional[str] = "free"
    notes: Optional[str] = None

    @field_validator("payment_method")
    @classmethod
    def validate_payment(cls, v):
        v = (v or "free").lower()
        if v not in SUPPORTED_PAYMENT_METHODS:
            raise ValueError(f"Unsupported payment method: {v}")
        return v

    @field_validator("notes")
    @classmethod
    def validate_notes(cls, v):
        if v and len(v) > 1000:
            raise ValueError("Notes must be at most 1000 characters")
        return v


class PaymentUpdate(BaseModel):
    payment_status: str


class PaymentProcessRequest(BaseModel):
    payment_method: str
    amount: float
    force_decline: bool = False


def _serialize_row(row: dict) -> dict:
    return {k: str(v) if isinstance(v, datetime) else v for k, v in row.items()}


def generate_ticket_number(reg_id: int) -> str:
    prefix = "TKT"
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{prefix}-{reg_id:04d}-{suffix}"


def process_payment_mock(
    payment_method: str, amount: float, force_decline: bool = False
) -> dict:
    method = (payment_method or "free").lower()
    if method == "credit_card":
        method = "card"
    if method not in SUPPORTED_PAYMENT_METHODS:
        raise HTTPException(
            status_code=400, detail=f"Unsupported payment method: {payment_method}"
        )
    if amount < 0:
        raise HTTPException(status_code=400, detail="Payment amount cannot be negative")
    if method == "free" or amount == 0:
        return {
            "status": "paid",
            "gateway": "simulated-free",
            "reference": f"FREE-{secrets.token_hex(4).upper()}",
        }
    if force_decline or random.random() < 0.05:
        return {
            "status": "failed",
            "gateway": f"simulated-{method}",
            "reference": f"DECLINED-{secrets.token_hex(4).upper()}",
        }
    return {
        "status": "paid",
        "gateway": f"simulated-{method}",
        "reference": f"TXN-{secrets.token_hex(8).upper()}",
    }


@app.on_event("startup")
def startup():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(DB_SCHEMA)
            cur.execute(
                "ALTER TABLE registrations ADD COLUMN IF NOT EXISTS payment_reference VARCHAR(100)"
            )
            cur.execute(
                "ALTER TABLE registrations ADD COLUMN IF NOT EXISTS payment_gateway VARCHAR(50)"
            )
            cur.execute(
                "ALTER TABLE registrations ADD COLUMN IF NOT EXISTS payment_processed_at TIMESTAMP"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_reg_user ON registrations(user_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_reg_event_status ON registrations(event_id, status)"
            )
        conn.commit()


@app.get("/health")
def health():
    return {"status": "healthy", "service": "registration-service"}


@app.post("/registrations")
def register(
    reg: RegistrationCreate,
    user=Depends(require_role("attendee", "organizer", "super_admin")),
):
    user_id = user["user_id"]
    client = get_http_client()
    headers = {"X-Service-Key": SERVICE_API_KEY}

    try:
        event_resp = client.get(
            f"{EVENT_SERVICE_URL}/events/{reg.event_id}", headers=headers
        )
        if event_resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Event not found")
        if event_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not fetch event details")
        event_data = event_resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Event service unavailable")

    increment_done = False
    try:
        resp = client.patch(
            f"{EVENT_SERVICE_URL}/events/{reg.event_id}/increment-registration",
            headers=headers,
        )
        if resp.status_code == 409:
            raise HTTPException(status_code=409, detail="Event is full")
        elif resp.status_code != 200:
            raise HTTPException(
                status_code=400, detail="Could not verify event capacity"
            )
        increment_done = True
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Event service unavailable")

    amount = float(event_data.get("ticket_price") or 0)
    payment_result = process_payment_mock(reg.payment_method or "free", amount)
    if payment_result["status"] != "paid":
        if increment_done:
            try:
                client.patch(
                    f"{EVENT_SERVICE_URL}/events/{reg.event_id}/decrement-registration",
                    headers=headers,
                )
            except Exception:
                pass
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Payment failed",
                "payment_status": payment_result["status"],
                "payment_reference": payment_result["reference"],
                "payment_gateway": payment_result["gateway"],
            },
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            try:
                cur.execute(
                    """INSERT INTO registrations (
                        user_id, event_id, payment_method, payment_status,
                        payment_reference, payment_gateway, payment_processed_at, notes
                    ) VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s) RETURNING *""",
                    (
                        user_id,
                        reg.event_id,
                        reg.payment_method,
                        payment_result["status"],
                        payment_result["reference"],
                        payment_result["gateway"],
                        reg.notes,
                    ),
                )
                new_reg = dict(cur.fetchone())
                ticket = generate_ticket_number(new_reg["id"])
                cur.execute(
                    "UPDATE registrations SET ticket_number=%s WHERE id=%s",
                    (ticket, new_reg["id"]),
                )
                new_reg["ticket_number"] = ticket
                conn.commit()
                new_reg = _serialize_row(new_reg)
            except psycopg2.IntegrityError:
                conn.rollback()
                if increment_done:
                    try:
                        client.patch(
                            f"{EVENT_SERVICE_URL}/events/{reg.event_id}/decrement-registration",
                            headers=headers,
                        )
                    except Exception:
                        pass
                raise HTTPException(
                    status_code=409, detail="User already registered for this event"
                )

    try:
        r = get_redis()
        r.publish(
            "notification_events",
            json.dumps(
                {
                    "event": "registration_confirmed",
                    "user_id": user_id,
                    "event_id": reg.event_id,
                    "ticket_number": ticket,
                    "registration_id": new_reg["id"],
                }
            ),
        )
    except Exception:
        pass

    publish_event(
        "registration.confirmed",
        {
            "event": "registration_confirmed",
            "user_id": user_id,
            "event_id": reg.event_id,
            "ticket_number": ticket,
            "registration_id": new_reg["id"],
        },
    )

    return {"message": "Registration successful", "registration": new_reg}


@app.get("/registrations")
def list_registrations(user: dict = Depends(get_current_user)):
    if user["role"] == "super_admin":
        with get_db() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(
                    "SELECT * FROM registrations ORDER BY registration_date DESC LIMIT 100"
                )
                regs = [_serialize_row(dict(r)) for r in cur.fetchall()]
                return {"registrations": regs, "total": len(regs)}
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM registrations WHERE user_id=%s ORDER BY registration_date DESC LIMIT 100",
                (user["user_id"],),
            )
            regs = [_serialize_row(dict(r)) for r in cur.fetchall()]
            return {"registrations": regs, "total": len(regs)}


@app.get("/registrations/{registration_id}")
def get_registration(registration_id: int, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM registrations WHERE id=%s", (registration_id,))
            reg = cur.fetchone()
            if not reg:
                raise HTTPException(status_code=404, detail="Registration not found")
            reg = dict(reg)
            if user["role"] != "super_admin" and reg["user_id"] != user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")
            return _serialize_row(reg)


@app.get("/registrations/user/{user_id}")
def get_user_registrations(user_id: int, user: dict = Depends(get_current_user)):
    if user["role"] != "super_admin" and user["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM registrations WHERE user_id=%s ORDER BY registration_date DESC",
                (user_id,),
            )
            regs = [_serialize_row(dict(r)) for r in cur.fetchall()]
            return {"registrations": regs, "total": len(regs)}


@app.get("/registrations/event/{event_id}")
def get_event_registrations(event_id: int, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM registrations WHERE event_id=%s AND status='confirmed' ORDER BY registration_date",
                (event_id,),
            )
            regs = [_serialize_row(dict(r)) for r in cur.fetchall()]
            return {"registrations": regs, "total": len(regs)}


@app.patch("/registrations/{registration_id}/payment")
def update_payment(
    registration_id: int,
    payment: PaymentUpdate,
    user=Depends(require_role("super_admin")),
):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "UPDATE registrations SET payment_status=%s WHERE id=%s RETURNING id, payment_status",
                (payment.payment_status, registration_id),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Registration not found")
            conn.commit()
            return {"message": "Payment status updated", "registration": dict(row)}


@app.post("/registrations/{registration_id}/process-payment")
def process_registration_payment(
    registration_id: int,
    payment: PaymentProcessRequest,
    user: dict = Depends(get_current_user),
):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, user_id, payment_status FROM registrations WHERE id=%s",
                (registration_id,),
            )
            reg = cur.fetchone()
            if not reg:
                raise HTTPException(status_code=404, detail="Registration not found")
            if user["role"] != "super_admin" and reg["user_id"] != user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")
            result = process_payment_mock(
                payment.payment_method, payment.amount, payment.force_decline
            )
            cur.execute(
                """UPDATE registrations SET payment_method=%s, payment_status=%s,
                   payment_reference=%s, payment_gateway=%s, payment_processed_at=NOW()
                   WHERE id=%s RETURNING id, payment_method, payment_status, payment_reference, payment_gateway, payment_processed_at""",
                (
                    payment.payment_method,
                    result["status"],
                    result["reference"],
                    result["gateway"],
                    registration_id,
                ),
            )
            updated = _serialize_row(dict(cur.fetchone()))
            conn.commit()
            return {"message": "Payment processed", "payment": updated}


@app.delete("/registrations/{registration_id}")
def cancel_registration(registration_id: int, user: dict = Depends(get_current_user)):
    headers = {"X-Service-Key": SERVICE_API_KEY}
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT user_id, event_id FROM registrations WHERE id=%s AND status='confirmed'",
                (registration_id,),
            )
            reg = cur.fetchone()
            if not reg:
                raise HTTPException(
                    status_code=404,
                    detail="Registration not found or already cancelled",
                )
            if user["role"] != "super_admin" and reg["user_id"] != user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")
            event_id = reg["event_id"]
            cur.execute(
                "UPDATE registrations SET status='cancelled' WHERE id=%s RETURNING id, event_id",
                (registration_id,),
            )
            row = cur.fetchone()
            conn.commit()

    try:
        get_http_client().patch(
            f"{EVENT_SERVICE_URL}/events/{event_id}/decrement-registration",
            headers=headers,
        )
    except Exception:
        pass

    publish_event(
        "registration.cancelled",
        {
            "event": "registration_cancelled",
            "registration_id": registration_id,
            "event_id": event_id,
        },
    )

    return {"message": "Registration cancelled"}
