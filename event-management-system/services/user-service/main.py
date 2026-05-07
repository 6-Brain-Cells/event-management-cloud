from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, EmailStr
from typing import Optional
import psycopg2
import psycopg2.extras
import os
import hashlib
import secrets
import redis
import json
from datetime import datetime

app = FastAPI(title="User Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
Instrumentator().instrument(app).expose(app, endpoint="/metrics")

# DB connection
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

# Models
class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    full_name: str

class UserLogin(BaseModel):
    email: str
    password: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[str] = None

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

# Init DB table
@app.on_event("startup")
def startup():
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(50) UNIQUE NOT NULL,
                email VARCHAR(100) UNIQUE NOT NULL,
                password_hash VARCHAR(200) NOT NULL,
                full_name VARCHAR(100),
                created_at TIMESTAMP DEFAULT NOW(),
                is_active BOOLEAN DEFAULT TRUE
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"DB init error: {e}")

@app.get("/health")
def health():
    return {"status": "healthy", "service": "user-service"}

@app.get("/users/health")
def users_health():
    return {"status": "healthy", "service": "user-service"}

@app.post("/users/register")
def register(user: UserCreate):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "INSERT INTO users (username, email, password_hash, full_name) VALUES (%s, %s, %s, %s) RETURNING id, username, email, full_name, created_at",
            (user.username, user.email, hash_password(user.password), user.full_name)
        )
        new_user = dict(cur.fetchone())
        new_user["created_at"] = str(new_user["created_at"])
        conn.commit()

        # Publish event to Redis
        try:
            r = get_redis()
            r.publish("user_events", json.dumps({
                "event": "user_registered",
                "user_id": new_user["id"],
                "email": new_user["email"],
                "full_name": new_user["full_name"]
            }))
        except Exception:
            pass  # Non-critical

        return {"message": "User registered successfully", "user": new_user}
    except psycopg2.IntegrityError:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Username or email already exists")
    finally:
        cur.close()
        conn.close()

@app.post("/users/login")
def login(credentials: UserLogin):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, username, email, full_name FROM users WHERE email=%s AND password_hash=%s AND is_active=TRUE",
            (credentials.email, hash_password(credentials.password))
        )
        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        token = secrets.token_hex(32)
        # Store token in Redis with 24h TTL
        try:
            r = get_redis()
            r.setex(f"token:{token}", 86400, json.dumps(dict(user)))
        except Exception:
            pass
        return {"token": token, "user": dict(user)}
    finally:
        cur.close()
        conn.close()

@app.get("/users/{user_id}")
def get_user(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, username, email, full_name, created_at FROM users WHERE id=%s AND is_active=TRUE", (user_id,))
        user = cur.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        result = dict(user)
        result["created_at"] = str(result["created_at"])
        return result
    finally:
        cur.close()
        conn.close()

@app.get("/users")
def list_users():
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, username, email, full_name, created_at FROM users WHERE is_active=TRUE ORDER BY id")
        users = [dict(r) for r in cur.fetchall()]
        for u in users:
            u["created_at"] = str(u["created_at"])
        return {"users": users, "total": len(users)}
    finally:
        cur.close()
        conn.close()

@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute("UPDATE users SET is_active=FALSE WHERE id=%s", (user_id,))
        conn.commit()
        return {"message": "User deactivated"}
    finally:
        cur.close()
        conn.close()
