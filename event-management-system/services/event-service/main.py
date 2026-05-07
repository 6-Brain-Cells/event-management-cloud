from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, List
import psycopg2
import psycopg2.extras
import os
import redis
import json
from datetime import datetime

app = FastAPI(title="Event Service", version="1.0.0")

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

class EventCreate(BaseModel):
    title: str
    description: str
    event_type: str  # conference, workshop, seminar
    start_date: str
    end_date: str
    location: str
    max_capacity: int
    organizer_id: int
    ticket_price: float = 0.0

class EventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    location: Optional[str] = None
    max_capacity: Optional[int] = None
    ticket_price: Optional[float] = None

@app.on_event("startup")
def startup():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
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
                created_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB init error: {e}")

@app.get("/health")
def health():
    return {"status": "healthy", "service": "event-service"}

@app.get("/events/health")
def events_health():
    return {"status": "healthy", "service": "event-service"}

@app.post("/events")
def create_event(event: EventCreate):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO events (title, description, event_type, start_date, end_date,
                location, max_capacity, organizer_id, ticket_price)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING *
        """, (event.title, event.description, event.event_type,
              event.start_date, event.end_date, event.location,
              event.max_capacity, event.organizer_id, event.ticket_price))
        new_event = dict(cur.fetchone())
        for k, v in new_event.items():
            if isinstance(v, datetime):
                new_event[k] = str(v)
        conn.commit()

        # Publish to Redis
        try:
            r = get_redis()
            r.publish("event_events", json.dumps({
                "event": "event_created",
                "event_id": new_event["id"],
                "title": new_event["title"],
                "organizer_id": new_event["organizer_id"]
            }))
        except Exception:
            pass

        return {"message": "Event created", "event": new_event}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        cur.close()
        conn.close()

@app.get("/events")
def list_events(event_type: Optional[str] = None, status: str = "active"):
    conn = get_db()
    cur = conn.cursor()
    try:
        if event_type:
            cur.execute("SELECT * FROM events WHERE status=%s AND event_type=%s ORDER BY start_date", (status, event_type))
        else:
            cur.execute("SELECT * FROM events WHERE status=%s ORDER BY start_date", (status,))
        events = []
        for row in cur.fetchall():
            r = dict(row)
            for k, v in r.items():
                if isinstance(v, datetime):
                    r[k] = str(v)
            events.append(r)
        return {"events": events, "total": len(events)}
    finally:
        cur.close()
        conn.close()

@app.get("/events/{event_id}")
def get_event(event_id: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM events WHERE id=%s", (event_id,))
        event = cur.fetchone()
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        result = dict(event)
        for k, v in result.items():
            if isinstance(v, datetime):
                result[k] = str(v)
        return result
    finally:
        cur.close()
        conn.close()

@app.put("/events/{event_id}")
def update_event(event_id: int, update: EventUpdate):
    conn = get_db()
    cur = conn.cursor()
    try:
        fields = {k: v for k, v in update.dict().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=400, detail="No fields to update")
        set_clause = ", ".join(f"{k}=%s" for k in fields)
        cur.execute(f"UPDATE events SET {set_clause} WHERE id=%s RETURNING id, title, status", 
                    list(fields.values()) + [event_id])
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Event not found")
        conn.commit()
        return {"message": "Event updated", "event": dict(row)}
    finally:
        cur.close()
        conn.close()

@app.patch("/events/{event_id}/increment-registration")
def increment_registration(event_id: int):
    """Called internally by registration service"""
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE events SET registered_count = registered_count + 1
            WHERE id=%s AND registered_count < max_capacity
            RETURNING id, registered_count, max_capacity
        """, (event_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=409, detail="Event full or not found")
        conn.commit()
        return dict(row)
    finally:
        cur.close()
        conn.close()

@app.delete("/events/{event_id}")
def cancel_event(event_id: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE events SET status='cancelled' WHERE id=%s", (event_id,))
        conn.commit()
        return {"message": "Event cancelled"}
    finally:
        cur.close()
        conn.close()
