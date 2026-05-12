from contextlib import contextmanager
from fastapi import FastAPI, HTTPException, Depends, Security, Header
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
from datetime import datetime
import pika
import math

app = FastAPI(title="Event Service", version="2.0.0")

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
CACHE_TTL = int(os.getenv("CACHE_TTL", "30"))
DEFAULT_PAGE_SIZE = 20
MAX_PAGE_SIZE = 100

security = HTTPBearer()
security_optional = HTTPBearer(auto_error=False)

_db_pool = None
_redis_client = None
_rabbitmq_channel = None


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


DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    description TEXT,
    event_type VARCHAR(50) NOT NULL,
    start_date TIMESTAMP NOT NULL,
    end_date TIMESTAMP NOT NULL,
    location VARCHAR(200),
    max_capacity INT NOT NULL DEFAULT 100,
    registered_count INT DEFAULT 0,
    organizer_id INT NOT NULL,
    ticket_price DECIMAL(10,2) DEFAULT 0.00,
    status VARCHAR(20) DEFAULT 'active',
    version INT NOT NULL DEFAULT 1,
    created_at TIMESTAMP DEFAULT NOW()
)
"""

DB_MIGRATION_VERSION = """
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='events' AND column_name='version'
    ) THEN
        ALTER TABLE events ADD COLUMN version INT NOT NULL DEFAULT 1;
    END IF;
END $$;
"""


def _get_pool():
    global _db_pool
    if _db_pool is None or _db_pool.closed:
        _db_pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=int(os.getenv("DB_POOL_MIN", "2")),
            maxconn=int(os.getenv("DB_POOL_MAX", "10")),
            host=os.getenv("DB_HOST", "postgres"),
            port=os.getenv("DB_PORT", "5432"),
            dbname=os.getenv("DB_NAME", "eventdb"),
            user=os.getenv("DB_USER", "postgres"),
            password=os.getenv("DB_PASSWORD", "postgres"),
            connect_timeout=int(os.getenv("DB_CONNECT_TIMEOUT", "5")),
            options="-c statement_timeout=5000",
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


@contextmanager
def get_db():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.set_session(autocommit=False)
        yield conn
    finally:
        pool.putconn(conn)


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


def verify_service_or_admin(
    credentials: HTTPAuthorizationCredentials = Security(security_optional),
    x_service_key: Optional[str] = Header(None, alias="X-Service-Key"),
):
    if x_service_key and x_service_key == SERVICE_API_KEY:
        return {"role": "service", "user_id": 0}
    if credentials:
        user = decode_token(credentials.credentials)
        if user.get("role") == "super_admin":
            return user
    raise HTTPException(status_code=403, detail="Access denied")


def verify_service_or_any_user(
    credentials: HTTPAuthorizationCredentials = Security(security_optional),
    x_service_key: Optional[str] = Header(None, alias="X-Service-Key"),
):
    if x_service_key and x_service_key == SERVICE_API_KEY:
        return {"role": "service", "user_id": 0}
    if credentials:
        return decode_token(credentials.credentials)
    raise HTTPException(status_code=401, detail="Not authenticated")


class EventCreate(BaseModel):
    title: str
    description: str
    event_type: str
    start_date: str
    end_date: str
    location: str
    max_capacity: int
    organizer_id: Optional[int] = None
    ticket_price: float = 0.0

    @field_validator("title")
    @classmethod
    def validate_title(cls, v):
        v = v.strip()
        if not v or len(v) > 200:
            raise ValueError("Title must be 1-200 characters")
        return v

    @field_validator("location")
    @classmethod
    def validate_location(cls, v):
        v = v.strip() if v else v
        if v and len(v) > 200:
            raise ValueError("Location must be at most 200 characters")
        return v

    @field_validator("max_capacity")
    @classmethod
    def validate_capacity(cls, v):
        if v < 1 or v > 100000:
            raise ValueError("Max capacity must be 1-100000")
        return v

    @field_validator("ticket_price")
    @classmethod
    def validate_price(cls, v):
        if v < 0 or v > 999999:
            raise ValueError("Ticket price must be 0-999999")
        return v


class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    max_capacity: Optional[int] = None
    ticket_price: Optional[float] = None
    version: int


def _parse_dt(value: str) -> datetime:
    v = (value or "").strip()
    try:
        return datetime.fromisoformat(v)
    except ValueError:
        if "T" in v and len(v) == 16:
            return datetime.fromisoformat(v + ":00")
        raise


def _serialize_row(row: dict) -> dict:
    return {k: str(v) if isinstance(v, datetime) else v for k, v in row.items()}


def _invalidate_events_cache():
    try:
        r = get_redis()
        for key in r.scan_iter("events:list:*"):
            r.delete(key)
    except Exception:
        pass


@app.on_event("startup")
def startup():
    try:
        from alembic.config import Config as AlembicConfig
        from alembic import command as alembic_command

        alembic_cfg = AlembicConfig("alembic.ini")
        db_url = (
            f"postgresql://{os.getenv('DB_USER', 'postgres')}:"
            f"{os.getenv('DB_PASSWORD', 'postgres')}@"
            f"{os.getenv('DB_HOST', 'postgres')}:"
            f"{os.getenv('DB_PORT', '5432')}/"
            f"{os.getenv('DB_NAME', 'eventdb')}"
        )
        alembic_cfg.set_main_option("sqlalchemy.url", db_url)
        alembic_command.upgrade(alembic_cfg, "head")
    except Exception:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(DB_SCHEMA)
                cur.execute(DB_MIGRATION_VERSION)
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_status_type ON events(status, event_type)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_start_date ON events(start_date)"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_events_organizer ON events(organizer_id)"
                )
            conn.commit()


@app.get("/health")
def health():
    return {"status": "healthy", "service": "event-service"}


@app.post("/events")
def create_event(
    event: EventCreate, user=Depends(require_role("organizer", "super_admin"))
):
    start_dt = _parse_dt(event.start_date)
    end_dt = _parse_dt(event.end_date)
    if end_dt <= start_dt:
        raise HTTPException(status_code=400, detail="end_date must be after start_date")

    organizer_id = event.organizer_id
    if user["role"] == "super_admin" and organizer_id:
        pass
    else:
        organizer_id = user["user_id"]

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            try:
                cur.execute(
                    """
                    INSERT INTO events (title, description, event_type, start_date, end_date,
                        location, max_capacity, organizer_id, ticket_price)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING *
                """,
                    (
                        event.title,
                        event.description,
                        event.event_type,
                        start_dt,
                        end_dt,
                        event.location,
                        event.max_capacity,
                        organizer_id,
                        event.ticket_price,
                    ),
                )
                new_event = _serialize_row(dict(cur.fetchone()))
                conn.commit()
            except Exception as e:
                conn.rollback()
                raise HTTPException(status_code=400, detail=str(e))

    try:
        r = get_redis()
        r.publish(
            "event_events",
            json.dumps(
                {
                    "event": "event_created",
                    "event_id": new_event["id"],
                    "title": new_event["title"],
                    "organizer_id": new_event["organizer_id"],
                }
            ),
        )
    except Exception:
        pass

    publish_event(
        "event.created",
        {
            "event": "event_created",
            "event_id": new_event["id"],
            "title": new_event["title"],
            "organizer_id": new_event["organizer_id"],
        },
    )

    _invalidate_events_cache()

    return {"message": "Event created", "event": new_event}


@app.get("/events")
def list_events(
    event_type: Optional[str] = None,
    status: str = "active",
    page: int = 1,
    page_size: int = DEFAULT_PAGE_SIZE,
    user: dict = Depends(verify_service_or_any_user),
):
    page = max(1, page)
    page_size = min(max(1, page_size), MAX_PAGE_SIZE)

    cache_key = f"events:list:{status}:{event_type or 'all'}:{page}:{page_size}"
    if user.get("role") == "super_admin" and status == "all":
        cache_key += ":admin"

    try:
        r = get_redis()
        cached = r.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            base_where = ""
            params = []

            if user.get("role") == "super_admin" and status == "all":
                if event_type:
                    base_where = "WHERE event_type=%s"
                    params = [event_type]
            elif event_type:
                base_where = "WHERE status=%s AND event_type=%s"
                params = [status, event_type]
            else:
                base_where = "WHERE status=%s"
                params = [status]

            cur.execute(f"SELECT COUNT(*) as cnt FROM events {base_where}", params)
            total = cur.fetchone()["cnt"]

            offset = (page - 1) * page_size
            cur.execute(
                f"SELECT * FROM events {base_where} ORDER BY start_date LIMIT %s OFFSET %s",
                params + [page_size, offset],
            )
            events = [_serialize_row(dict(r)) for r in cur.fetchall()]

    total_pages = math.ceil(total / page_size) if total > 0 else 1
    result = {
        "events": events,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }

    try:
        r = get_redis()
        r.setex(cache_key, CACHE_TTL, json.dumps(result, default=str))
    except Exception:
        pass

    return result


@app.get("/events/{event_id}")
def get_event(event_id: int, user: dict = Depends(verify_service_or_any_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM events WHERE id=%s", (event_id,))
            event = cur.fetchone()
            if not event:
                raise HTTPException(status_code=404, detail="Event not found")
            return _serialize_row(dict(event))


@app.put("/events/{event_id}")
def update_event(
    event_id: int, update: EventUpdate, user: dict = Depends(get_current_user)
):
    if user["role"] not in ("organizer", "super_admin"):
        raise HTTPException(
            status_code=403, detail="Only organizers or admins can update events"
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT organizer_id, version FROM events WHERE id=%s",
                (event_id,),
            )
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Event not found")
            if (
                user["role"] == "organizer"
                and existing["organizer_id"] != user["user_id"]
            ):
                raise HTTPException(
                    status_code=403, detail="You can only update your own events"
                )
            if existing["version"] != update.version:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Optimistic concurrency conflict: event was modified by another request",
                        "current_version": existing["version"],
                        "provided_version": update.version,
                    },
                )

            fields = {
                k: v
                for k, v in update.dict().items()
                if v is not None and k != "version"
            }
            if not fields:
                raise HTTPException(status_code=400, detail="No fields to update")
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            set_clause += ", version=version+1"
            cur.execute(
                f"UPDATE events SET {set_clause} WHERE id=%s AND version=%s RETURNING *",
                list(fields.values()) + [event_id, update.version],
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(
                    status_code=409,
                    detail="Optimistic concurrency conflict: event was modified concurrently",
                )
            conn.commit()
            _invalidate_events_cache()
            return {"message": "Event updated", "event": _serialize_row(dict(row))}


@app.patch("/events/{event_id}/increment-registration")
def increment_registration(event_id: int, _auth=Depends(verify_service_or_admin)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE events SET registered_count = registered_count + 1
                WHERE id=%s AND registered_count < max_capacity
                RETURNING id, registered_count, max_capacity
            """,
                (event_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=409, detail="Event full or not found")
            conn.commit()
            return dict(row)


@app.patch("/events/{event_id}/decrement-registration")
def decrement_registration(event_id: int, _auth=Depends(verify_service_or_admin)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                UPDATE events SET registered_count = GREATEST(registered_count - 1, 0)
                WHERE id=%s
                RETURNING id, registered_count, max_capacity
            """,
                (event_id,),
            )
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Event not found")
            conn.commit()
            return dict(row)


@app.delete("/events/{event_id}")
def cancel_event(
    event_id: int,
    version: int,
    user: dict = Depends(get_current_user),
):
    if user["role"] not in ("organizer", "super_admin"):
        raise HTTPException(
            status_code=403, detail="Only organizers or admins can cancel events"
        )

    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT organizer_id, version FROM events WHERE id=%s",
                (event_id,),
            )
            existing = cur.fetchone()
            if not existing:
                raise HTTPException(status_code=404, detail="Event not found")
            if (
                user["role"] == "organizer"
                and existing["organizer_id"] != user["user_id"]
            ):
                raise HTTPException(
                    status_code=403, detail="You can only cancel your own events"
                )
            if existing["version"] != version:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "Optimistic concurrency conflict: event was modified by another request",
                        "current_version": existing["version"],
                        "provided_version": version,
                    },
                )

            cur.execute(
                "UPDATE events SET status='cancelled', version=version+1 WHERE id=%s AND version=%s",
                (event_id, version),
            )
            if cur.rowcount == 0:
                raise HTTPException(
                    status_code=409,
                    detail="Optimistic concurrency conflict: event was modified concurrently",
                )
            conn.commit()
            _invalidate_events_cache()
            return {"message": "Event cancelled"}
