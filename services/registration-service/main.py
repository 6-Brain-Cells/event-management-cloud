from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import psycopg2
import psycopg2.extras
import os
import redis
import json
import httpx
from datetime import datetime

app = FastAPI(title="Registration Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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

@app.get("/health")
def health():
    return {"status": "healthy", "service": "registration-service"}

@app.post("/registrations")
def register(reg: RegistrationCreate):
    # Check with event service that capacity exists
    try:
        resp = httpx.patch(f"{EVENT_SERVICE_URL}/events/{reg.event_id}/increment-registration")
        if resp.status_code == 409:
            raise HTTPException(status_code=409, detail="Event is full")
        elif resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Could not verify event capacity")
    except httpx.ConnectError:
        raise HTTPException(status_code=503, detail="Event service unavailable")

    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO registrations (user_id, event_id, payment_method, notes)
            VALUES (%s, %s, %s, %s)
            RETURNING *
        """, (reg.user_id, reg.event_id, reg.payment_method, reg.notes))
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
        raise HTTPException(status_code=409, detail="User already registered for this event")
    finally:
        cur.close()
        conn.close()

@app.get("/registrations")
def list_registrations():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT * FROM registrations ORDER BY registration_date DESC LIMIT 100")
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
