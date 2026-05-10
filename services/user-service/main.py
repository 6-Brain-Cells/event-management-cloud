from contextlib import contextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel
from typing import Optional
import psycopg2
import psycopg2.extras
import psycopg2.pool
import os
import redis
import json
import secrets
from datetime import datetime
import bcrypt as _bcrypt
import pika

app = FastAPI(title="User Service", version="1.0.0")

Instrumentator().instrument(app).expose(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(200) NOT NULL,
    full_name VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
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


@contextmanager
def get_db():
    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.set_session(autocommit=False)
        yield conn
    finally:
        pool.putconn(conn)


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
    return _bcrypt.hashpw(password.encode("utf-8"), _bcrypt.gensalt(rounds=12)).decode(
        "utf-8"
    )


def verify_password(password: str, hashed: str) -> bool:
    return _bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))


@app.on_event("startup")
def startup():
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(DB_SCHEMA)
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE is_active=TRUE"
            )
        conn.commit()


@app.get("/health")
def health():
    return {"status": "healthy", "service": "user-service"}


@app.post("/users/register")
def register(user: UserCreate):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            try:
                cur.execute(
                    "INSERT INTO users (username, email, password_hash, full_name) VALUES (%s, %s, %s, %s) RETURNING id, username, email, full_name, created_at",
                    (
                        user.username,
                        user.email,
                        hash_password(user.password),
                        user.full_name,
                    ),
                )
                new_user = dict(cur.fetchone())
                new_user["created_at"] = str(new_user["created_at"])
                conn.commit()
            except psycopg2.IntegrityError:
                conn.rollback()
                raise HTTPException(
                    status_code=400, detail="Username or email already exists"
                )

    try:
        r = get_redis()
        r.publish(
            "user_events",
            json.dumps(
                {
                    "event": "user_registered",
                    "user_id": new_user["id"],
                    "email": new_user["email"],
                    "full_name": new_user["full_name"],
                }
            ),
        )
    except Exception:
        pass

    publish_event(
        "user.registered",
        {
            "event": "user_registered",
            "user_id": new_user["id"],
            "email": new_user["email"],
            "full_name": new_user["full_name"],
        },
    )

    return {"message": "User registered successfully", "user": new_user}


@app.post("/users/login")
def login(credentials: UserLogin):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, username, email, full_name, password_hash FROM users WHERE email=%s AND is_active=TRUE",
                (credentials.email,),
            )
            user = cur.fetchone()
            if not user or not verify_password(
                credentials.password, user["password_hash"]
            ):
                raise HTTPException(status_code=401, detail="Invalid credentials")
            user.pop("password_hash", None)

    token = secrets.token_hex(32)
    try:
        r = get_redis()
        r.setex(f"token:{token}", 86400, json.dumps(dict(user)))
    except Exception:
        pass
    return {"token": token, "user": dict(user)}


@app.get("/users/{user_id}")
def get_user(user_id: int):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, username, email, full_name, created_at FROM users WHERE id=%s AND is_active=TRUE",
                (user_id,),
            )
            user = cur.fetchone()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            result = dict(user)
            result["created_at"] = str(result["created_at"])
            return result


@app.get("/users")
def list_users():
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, username, email, full_name, created_at FROM users WHERE is_active=TRUE ORDER BY id"
            )
            users = [dict(r) for r in cur.fetchall()]
            for u in users:
                u["created_at"] = str(u["created_at"])
            return {"users": users, "total": len(users)}


@app.delete("/users/{user_id}")
def delete_user(user_id: int):
    with get_db() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET is_active=FALSE WHERE id=%s AND is_active=TRUE RETURNING id",
                (user_id,),
            )
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="User not found")
            conn.commit()
            return {"message": "User deactivated"}
