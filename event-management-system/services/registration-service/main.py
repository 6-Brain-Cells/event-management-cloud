from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from typing import Optional
import psycopg2
import psycopg2.extras
import os
import redis
import json
import httpx
from datetime import datetime
import random
import secrets

app = FastAPI(title="Registration Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

EVENT_SERVICE_URL = os.getenv("EVENT_SERVICE_URL", "http://event-service:8000")

def get_db():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "postgres"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "eventdb"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        cursor_factory=psycopg2.extras.RealDictCursor
    )

def get_redis():
    return redis.Redis(
        host=os.getenv("REDIS_HOST", "redis"),
        port=int(os.getenv("REDIS_PORT", "6379")),
        decode_responses=True
    )

class RegistrationCreate(BaseModel):
    user_id: int
    event_id: int
    payment_method: Optional[str] = "free"
    notes: Optional[str] = None

class PaymentUpdate(BaseModel):
    payment_status: str  # pending, paid, refunded

class PaymentProcessRequest(BaseModel):
    payment_method: str
    amount: float
    force_decline: bool = False

SUPPORTED_PAYMENT_METHODS = {"free", "card", "paypal", "bank_transfer"}

@app.on_event("startup")
def startup():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS registrations (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                event_id INT NOT NULL,
                registration_date TIMESTAMP DEFAULT NOW(),
                status VARCHAR(20) DEFAULT 'confirmed',
                payment_method VARCHAR(50) DEFAULT 'free',
                payment_status VARCHAR(20) DEFAULT 'pending',
                ticket_number VARCHAR(20) UNIQUE,
                notes TEXT,
                UNIQUE(user_id, event_id)
            )
        """)
        cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS payment_reference VARCHAR(100)")
        cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS payment_gateway VARCHAR(50)")
        cur.execute("ALTER TABLE registrations ADD COLUMN IF NOT EXISTS payment_processed_at TIMESTAMP")
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB init error: {e}")

def generate_ticket_number(reg_id: int) -> str:
    import random, string
    prefix = "TKT"
    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    return f"{prefix}-{reg_id:04d}-{suffix}"

def process_payment_mock(payment_method: str, amount: float, force_decline: bool = False) -> dict:
    method = (payment_method or "free").lower()
    if method not in SUPPORTED_PAYMENT_METHODS:
        raise HTTPException(status_code=400, detail=f"Unsupported payment method: {payment_method}")
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

@app.get("/health")
def health():
    return {"status": "healthy", "service": "registration-service"}

@app.get("/registrations/health")
def registrations_health():
    return {"status": "healthy", "service": "registration-service"}

@app.post("/registrations")
def register(reg: RegistrationCreate):
    # Get event and ticket price from event service
    try:
        event_resp = httpx.get(f"{EVENT_SERVICE_URL}/events/{reg.event_id}")
        if event_resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Event not found")
        if event_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not fetch event details")
        event_data = event_resp.json()
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Event service unavailable")

    amount = float(event_data.get("ticket_price") or 0)
    payment_result = process_payment_mock(reg.payment_method or "free", amount)
    if payment_result["status"] != "paid":
        raise HTTPException(
            status_code=402,
            detail={
                "message": "Payment failed",
                "payment_status": payment_result["status"],
                "payment_reference": payment_result["reference"],
                "payment_gateway": payment_result["gateway"],
            },
        )

    conn = get_db()
    cur = conn.cursor()
    increment_done = False
    try:
        # Fast duplicate guard to avoid consuming capacity for already-registered users.
        cur.execute(
            "SELECT id FROM registrations WHERE user_id=%s AND event_id=%s",
            (reg.user_id, reg.event_id),
        )
        if cur.fetchone():
            raise HTTPException(status_code=409, detail="User already registered for this event")

        # Check with event service that capacity exists.
        try:
            resp = httpx.patch(f"{EVENT_SERVICE_URL}/events/{reg.event_id}/increment-registration")
            if resp.status_code == 409:
                raise HTTPException(status_code=409, detail="Event is full")
            elif resp.status_code != 200:
                raise HTTPException(status_code=400, detail="Could not verify event capacity")
            increment_done = True
        except httpx.ConnectError:
            raise HTTPException(status_code=503, detail="Event service unavailable")

        cur.execute("""
            INSERT INTO registrations (
                user_id, event_id, payment_method, payment_status, payment_reference,
                payment_gateway, payment_processed_at, notes
            )
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
            RETURNING *
        """, (
            reg.user_id,
            reg.event_id,
            reg.payment_method,
            payment_result["status"],
            payment_result["reference"],
            payment_result["gateway"],
            reg.notes
        ))
        new_reg = dict(cur.fetchone())
        # Generate ticket number
        ticket = generate_ticket_number(new_reg["id"])
        cur.execute("UPDATE registrations SET ticket_number=%s WHERE id=%s", (ticket, new_reg["id"]))
        new_reg["ticket_number"] = ticket
        conn.commit()

        for k, v in new_reg.items():
            if isinstance(v, datetime):
                new_reg[k] = str(v)

        # Publish async notification event to Redis
        try:
            r = get_redis()
            r.publish("notification_events", json.dumps({
                "event": "registration_confirmed",
                "user_id": reg.user_id,
                "event_id": reg.event_id,
                "ticket_number": ticket,
                "registration_id": new_reg["id"]
            }))
        except Exception:
            pass

        return {"message": "Registration successful", "registration": new_reg}
    except psycopg2.IntegrityError:
        conn.rollback()
        if increment_done:
            try:
                httpx.patch(f"{EVENT_SERVICE_URL}/events/{reg.event_id}/decrement-registration")
            except Exception:
                pass
        raise HTTPException(status_code=409, detail="User already registered for this event")
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        if increment_done:
            try:
                httpx.patch(f"{EVENT_SERVICE_URL}/events/{reg.event_id}/decrement-registration")
            except Exception:
                pass
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()
        conn.close()

@app.get("/registrations/{registration_id}")
def get_registration(registration_id: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM registrations WHERE id=%s", (registration_id,))
        reg = cur.fetchone()
        if not reg:
            raise HTTPException(status_code=404, detail="Registration not found")
        result = dict(reg)
        for k, v in result.items():
            if isinstance(v, datetime):
                result[k] = str(v)
        return result
    finally:
        cur.close()
        conn.close()

@app.get("/registrations/user/{user_id}")
def get_user_registrations(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM registrations WHERE user_id=%s ORDER BY registration_date DESC", (user_id,))
        regs = []
        for row in cur.fetchall():
            r = dict(row)
            for k, v in r.items():
                if isinstance(v, datetime):
                    r[k] = str(v)
            regs.append(r)
        return {"registrations": regs, "total": len(regs)}
    finally:
        cur.close()
        conn.close()

@app.get("/registrations/event/{event_id}")
def get_event_registrations(event_id: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM registrations WHERE event_id=%s AND status='confirmed' ORDER BY registration_date", (event_id,))
        regs = []
        for row in cur.fetchall():
            r = dict(row)
            for k, v in r.items():
                if isinstance(v, datetime):
                    r[k] = str(v)
            regs.append(r)
        return {"registrations": regs, "total": len(regs)}
    finally:
        cur.close()
        conn.close()

@app.patch("/registrations/{registration_id}/payment")
def update_payment(registration_id: int, payment: PaymentUpdate):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "UPDATE registrations SET payment_status=%s WHERE id=%s RETURNING id, payment_status",
            (payment.payment_status, registration_id)
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Registration not found")
        conn.commit()
        return {"message": "Payment status updated", "registration": dict(row)}
    finally:
        cur.close()
        conn.close()

@app.post("/registrations/{registration_id}/process-payment")
def process_registration_payment(registration_id: int, payment: PaymentProcessRequest):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, payment_status FROM registrations WHERE id=%s", (registration_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Registration not found")

        result = process_payment_mock(payment.payment_method, payment.amount, payment.force_decline)
        cur.execute(
            """
            UPDATE registrations
            SET payment_method=%s, payment_status=%s, payment_reference=%s,
                payment_gateway=%s, payment_processed_at=NOW()
            WHERE id=%s
            RETURNING id, payment_method, payment_status, payment_reference, payment_gateway, payment_processed_at
            """,
            (payment.payment_method, result["status"], result["reference"], result["gateway"], registration_id)
        )
        updated = dict(cur.fetchone())
        if isinstance(updated.get("payment_processed_at"), datetime):
            updated["payment_processed_at"] = str(updated["payment_processed_at"])
        conn.commit()
        return {"message": "Payment processed", "payment": updated}
    finally:
        cur.close()
        conn.close()

@app.delete("/registrations/{registration_id}")
def cancel_registration(registration_id: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE registrations SET status='cancelled' WHERE id=%s RETURNING id, event_id", (registration_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Registration not found")
        conn.commit()
        return {"message": "Registration cancelled"}
    finally:
        cur.close()
        conn.close()
