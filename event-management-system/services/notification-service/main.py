from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import psycopg2
import psycopg2.extras
import os
import redis
import json
import threading
import httpx
from datetime import datetime

app = FastAPI(title="Notification Service", version="1.0.0")
WEBHOOK_URL = os.getenv("NOTIFICATION_WEBHOOK_URL", "").strip()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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

class NotificationCreate(BaseModel):
    user_id: int
    title: str
    message: str
    notification_type: str = "info"  # info, reminder, confirmation, cancellation

def deliver_webhook(payload: dict):
    """Optional outbound delivery channel for user-visible notifications."""
    if not WEBHOOK_URL:
        return
    try:
        with httpx.Client(timeout=5.0) as client:
            client.post(WEBHOOK_URL, json=payload)
    except Exception as e:
        print(f"[NOTIFY] Webhook delivery failed: {e}")

def save_notification(user_id: int, title: str, message: str, notification_type: str):
    """Save notification to DB"""
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                title VARCHAR(200) NOT NULL,
                message TEXT,
                notification_type VARCHAR(50) DEFAULT 'info',
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        cur.execute("""
            INSERT INTO notifications (user_id, title, message, notification_type)
            VALUES (%s, %s, %s, %s)
        """, (user_id, title, message, notification_type))
        conn.commit()
        cur.close()
        conn.close()
        print(f"[NOTIFY] Saved notification for user {user_id}: {title}")
        deliver_webhook(
            {
                "user_id": user_id,
                "title": title,
                "message": message,
                "notification_type": notification_type,
                "delivered_at": datetime.utcnow().isoformat() + "Z",
            }
        )
    except Exception as e:
        print(f"[NOTIFY] Error saving notification: {e}")

def redis_subscriber():
    """Background thread: subscribes to Redis channels for async events"""
    try:
        r = get_redis()
        pubsub = r.pubsub()
        pubsub.subscribe("notification_events", "user_events", "event_events")
        print("[NOTIFY] Subscribed to Redis channels")
        for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    event_type = data.get("event")

                    if event_type == "registration_confirmed":
                        save_notification(
                            user_id=data["user_id"],
                            title="Registration Confirmed",
                            message=f"Your registration is confirmed. Ticket: {data.get('ticket_number', 'N/A')}",
                            notification_type="confirmation"
                        )
                    elif event_type == "user_registered":
                        save_notification(
                            user_id=data["user_id"],
                            title="Welcome!",
                            message=f"Welcome {data.get('full_name', '')}! Your account has been created.",
                            notification_type="info"
                        )
                    elif event_type == "event_created":
                        print(f"[NOTIFY] New event created: {data.get('title')}")
                except Exception as e:
                    print(f"[NOTIFY] Error processing message: {e}")
    except Exception as e:
        print(f"[NOTIFY] Redis subscriber error: {e}")

@app.on_event("startup")
def startup():
    # Init notifications table
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                user_id INT NOT NULL,
                title VARCHAR(200) NOT NULL,
                message TEXT,
                notification_type VARCHAR(50) DEFAULT 'info',
                is_read BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB init error: {e}")

    # Start Redis subscriber in background thread
    t = threading.Thread(target=redis_subscriber, daemon=True)
    t.start()

@app.get("/health")
def health():
    return {"status": "healthy", "service": "notification-service"}

@app.get("/notifications/health")
def notifications_health():
    return {"status": "healthy", "service": "notification-service"}

@app.post("/notifications")
def create_notification(notif: NotificationCreate):
    """Manually create a notification (e.g., reminders triggered by organizers)"""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO notifications (user_id, title, message, notification_type)
            VALUES (%s, %s, %s, %s) RETURNING *
        """, (notif.user_id, notif.title, notif.message, notif.notification_type))
        new_notif = dict(cur.fetchone())
        new_notif["created_at"] = str(new_notif["created_at"])
        conn.commit()
        deliver_webhook(
            {
                "user_id": notif.user_id,
                "title": notif.title,
                "message": notif.message,
                "notification_type": notif.notification_type,
                "delivered_at": datetime.utcnow().isoformat() + "Z",
            }
        )
        return {"message": "Notification sent", "notification": new_notif}
    finally:
        cur.close()
        conn.close()

@app.get("/notifications/user/{user_id}")
def get_user_notifications(user_id: int, unread_only: bool = False):
    conn = get_db()
    cur = conn.cursor()
    try:
        if unread_only:
            cur.execute("SELECT * FROM notifications WHERE user_id=%s AND is_read=FALSE ORDER BY created_at DESC", (user_id,))
        else:
            cur.execute("SELECT * FROM notifications WHERE user_id=%s ORDER BY created_at DESC", (user_id,))
        notifs = []
        for row in cur.fetchall():
            r = dict(row)
            r["created_at"] = str(r["created_at"])
            notifs.append(r)
        return {"notifications": notifs, "total": len(notifs)}
    finally:
        cur.close()
        conn.close()

@app.patch("/notifications/{notification_id}/read")
def mark_read(notification_id: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE notifications SET is_read=TRUE WHERE id=%s RETURNING id", (notification_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Notification not found")
        conn.commit()
        return {"message": "Marked as read"}
    finally:
        cur.close()
        conn.close()

@app.post("/notifications/broadcast")
def broadcast(user_ids: list[int], title: str, message: str):
    """Send notification to multiple users"""
    conn = get_db()
    cur = conn.cursor()
    try:
        for uid in user_ids:
            cur.execute(
                "INSERT INTO notifications (user_id, title, message, notification_type) VALUES (%s, %s, %s, 'info')",
                (uid, title, message)
            )
            deliver_webhook(
                {
                    "user_id": uid,
                    "title": title,
                    "message": message,
                    "notification_type": "info",
                    "delivered_at": datetime.utcnow().isoformat() + "Z",
                }
            )
        conn.commit()
        return {"message": f"Broadcast sent to {len(user_ids)} users"}
    finally:
        cur.close()
        conn.close()
