from contextlib import contextmanager
from fastapi import FastAPI, HTTPException, Depends, Security
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from typing import Optional, List
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import json
import jwt
import threading
import pika
from datetime import datetime

app = FastAPI(title="Notification Service", version="2.0.0")

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

security = HTTPBearer()

_db_pool = None

DB_SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(200) NOT NULL,
    message TEXT,
    notification_type VARCHAR(50) DEFAULT 'info',
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
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


class NotificationCreate(BaseModel):
    user_id: int
    title: str
    message: str
    notification_type: str = "info"


class BroadcastRequest(BaseModel):
    user_ids: List[int]
    title: str
    message: str


def _serialize_row(row: dict) -> dict:
    return {k: str(v) if isinstance(v, datetime) else v for k, v in row.items()}


def save_notification(user_id: int, title: str, message: str, notification_type: str):
    try:
        with get_db() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO notifications (user_id, title, message, notification_type) VALUES (%s, %s, %s, %s)",
                    (user_id, title, message, notification_type),
                )
            conn.commit()
    except Exception as e:
        print(f"[NOTIFY] Error saving notification: {e}")


def _handle_message(data: dict):
    event_type = data.get("event")
    if event_type == "registration_confirmed":
        save_notification(
            user_id=data["user_id"],
            title="Registration Confirmed",
            message=f"Your registration is confirmed. Ticket: {data.get('ticket_number', 'N/A')}",
            notification_type="confirmation",
        )
    elif event_type == "user_registered":
        save_notification(
            user_id=data["user_id"],
            title="Welcome!",
            message=f"Welcome {data.get('full_name', '')}! Your account has been created.",
            notification_type="info",
        )
    elif event_type == "event_created":
        print(f"[NOTIFY] New event created: {data.get('title')}")
    elif event_type == "registration_cancelled":
        print(f"[NOTIFY] Registration cancelled: {data.get('registration_id')}")


def rabbitmq_consumer():
    try:
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
        ch = conn.channel()
        ch.exchange_declare(exchange="events", exchange_type="topic", durable=True)
        result = ch.queue_declare(queue="notification_queue", durable=True)
        queue_name = result.method.queue
        for routing_key in [
            "user.registered",
            "event.created",
            "registration.confirmed",
            "registration.cancelled",
        ]:
            ch.queue_bind(exchange="events", queue=queue_name, routing_key=routing_key)

        def callback(ch, method, properties, body):
            try:
                data = json.loads(body.decode("utf-8"))
                print(
                    f"[NOTIFY-RMQ] Received {method.routing_key}: {data.get('event')}"
                )
                _handle_message(data)
                ch.basic_ack(delivery_tag=method.delivery_tag)
            except Exception as e:
                print(f"[NOTIFY-RMQ] Error: {e}")
                ch.basic_nack(delivery_tag=method.delivery_tag, requeue=True)

        ch.basic_qos(prefetch_count=10)
        ch.basic_consume(queue=queue_name, on_message_callback=callback)
        print("[NOTIFY-RMQ] Consuming from RabbitMQ notification_queue")
        ch.start_consuming()
    except Exception as e:
        print(f"[NOTIFY-RMQ] RabbitMQ consumer error: {e}")


@app.on_event("startup")
def startup():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(DB_SCHEMA)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read)"
            )
        conn.commit()

    t = threading.Thread(target=rabbitmq_consumer, daemon=True)
    t.start()


@app.get("/health")
def health():
    return {"status": "healthy", "service": "notification-service"}


@app.post("/notifications")
def create_notification(
    notif: NotificationCreate, user=Depends(require_role("super_admin"))
):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "INSERT INTO notifications (user_id, title, message, notification_type) VALUES (%s, %s, %s, %s) RETURNING *",
                (notif.user_id, notif.title, notif.message, notif.notification_type),
            )
            new_notif = _serialize_row(dict(cur.fetchone()))
            conn.commit()
            return {"message": "Notification sent", "notification": new_notif}


@app.get("/notifications/user/{user_id}")
def get_user_notifications(
    user_id: int, unread_only: bool = False, user: dict = Depends(get_current_user)
):
    if user["role"] != "super_admin" and user["user_id"] != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if unread_only:
                cur.execute(
                    "SELECT * FROM notifications WHERE user_id=%s AND is_read=FALSE ORDER BY created_at DESC",
                    (user_id,),
                )
            else:
                cur.execute(
                    "SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC",
                    (user_id,),
                )
            notifs = [_serialize_row(dict(r)) for r in cur.fetchall()]
            return {"notifications": notifs, "total": len(notifs)}


@app.patch("/notifications/{notification_id}/read")
def mark_read(notification_id: int, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT user_id FROM notifications WHERE id=%s",
                (notification_id,),
            )
            notif = cur.fetchone()
            if not notif:
                raise HTTPException(status_code=404, detail="Notification not found")
            if user["role"] != "super_admin" and notif["user_id"] != user["user_id"]:
                raise HTTPException(status_code=403, detail="Access denied")
            cur.execute(
                "UPDATE notifications SET is_read=TRUE WHERE id=%s RETURNING id",
                (notification_id,),
            )
            conn.commit()
            return {"message": "Marked as read"}


@app.post("/notifications/broadcast")
def broadcast(req: BroadcastRequest, user=Depends(require_role("super_admin"))):
    if not req.user_ids:
        raise HTTPException(status_code=400, detail="user_ids cannot be empty")
    with get_db() as conn:
        with conn.cursor() as cur:
            args_str = ",".join(
                cur.mogrify("(%s,%s,%s,'info')", (uid, req.title, req.message)).decode(
                    "utf-8"
                )
                for uid in req.user_ids
            )
            cur.execute(
                f"INSERT INTO notifications (user_id, title, message, notification_type) VALUES {args_str}"
            )
            conn.commit()
            return {"message": f"Broadcast sent to {len(req.user_ids)} users"}
