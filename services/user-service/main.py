from contextlib import contextmanager
from fastapi import FastAPI, HTTPException, Depends, Security, Request
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
import logging
import uuid
import time
from datetime import datetime, timedelta, timezone
import sys
import bcrypt as _bcrypt
import pika


class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "user-service",
            "message": record.getMessage(),
            "logger": record.name,
        }
        if hasattr(record, "correlation_id"):
            log_entry["correlation_id"] = record.correlation_id
        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


_handler = logging.StreamHandler(sys.stderr)
_handler.setFormatter(JSONFormatter())
logging.basicConfig(
    handlers=[_handler], level=os.getenv("LOG_LEVEL", "INFO").upper(), force=True
)

logger = logging.getLogger(__name__)

app = FastAPI(title="User Service", version="3.0.0")

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


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID", str(uuid.uuid4()))
    request.state.correlation_id = correlation_id
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    response.headers["X-Correlation-ID"] = correlation_id
    logger.info(
        f"{request.method} {request.url.path} {response.status_code} {duration:.3f}s",
        extra={"correlation_id": correlation_id},
    )
    return response


JWT_SECRET = os.getenv("JWT_SECRET", "event-mgmt-secret-change-in-prod")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 24
VALID_ROLES = {"super_admin", "organizer", "attendee"}

security = HTTPBearer()

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
    role VARCHAR(20) DEFAULT 'attendee',
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
)
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


def create_jwt_token(user_data: dict) -> str:
    payload = {
        "user_id": user_data["id"],
        "username": user_data.get("username", ""),
        "email": user_data.get("email", ""),
        "role": user_data.get("role", "attendee"),
        "exp": datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
        "iat": datetime.now(timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


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


class UserCreate(BaseModel):
    username: str
    email: str
    password: str
    full_name: str
    role: Optional[str] = "attendee"

    @field_validator("username")
    @classmethod
    def validate_username(cls, v):
        v = v.strip()
        if not re.match(r"^[a-zA-Z0-9_]{3,50}$", v):
            raise ValueError(
                "Username must be 3-50 characters (alphanumeric and underscores only)"
            )
        return v

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        v = v.strip().lower()
        if not re.match(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$", v):
            raise ValueError("Invalid email format")
        return v

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        if len(v) > 128:
            raise ValueError("Password must be at most 128 characters")
        return v

    @field_validator("full_name")
    @classmethod
    def validate_full_name(cls, v):
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("Full name must be 1-100 characters")
        return v

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v and v not in VALID_ROLES:
            raise ValueError(f"Invalid role. Must be one of: {sorted(VALID_ROLES)}")
        return v or "attendee"


class UserLogin(BaseModel):
    email: str
    password: str


class RoleUpdate(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def validate_role(cls, v):
        if v not in VALID_ROLES:
            raise ValueError(f"Invalid role. Must be one of: {sorted(VALID_ROLES)}")
        return v


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
                cur.execute(
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(20) DEFAULT 'attendee'"
                )
                cur.execute(
                    "CREATE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE is_active=TRUE"
                )
            conn.commit()


@app.get("/health")
def health():
    return {"status": "healthy", "service": "user-service"}


@app.post("/users/register")
def register(user: UserCreate, request: Request):
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    logger.info(
        f"Registration attempt: username={user.username} email={user.email}",
        extra={"correlation_id": correlation_id},
    )
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            try:
                cur.execute(
                    "INSERT INTO users (username, email, password_hash, full_name, role) VALUES (%s, %s, %s, %s, %s) RETURNING id, username, email, full_name, role, created_at",
                    (
                        user.username,
                        user.email,
                        hash_password(user.password),
                        user.full_name,
                        user.role,
                    ),
                )
                new_user = dict(cur.fetchone())
                new_user["created_at"] = str(new_user["created_at"])
                conn.commit()
            except psycopg2.IntegrityError:
                conn.rollback()
                logger.warning(
                    f"Registration failed - duplicate: username={user.username} email={user.email}",
                    extra={"correlation_id": correlation_id},
                )
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

    logger.info(
        f"User registered: id={new_user['id']} username={new_user['username']}",
        extra={"correlation_id": correlation_id},
    )
    return {"message": "User registered successfully", "user": new_user}


@app.post("/users/login")
def login(credentials: UserLogin, request: Request):
    correlation_id = getattr(request.state, "correlation_id", "unknown")
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, username, email, full_name, role, password_hash FROM users WHERE email=%s AND is_active=TRUE",
                (credentials.email,),
            )
            user = cur.fetchone()
            if not user or not verify_password(
                credentials.password, user["password_hash"]
            ):
                logger.warning(
                    f"Login failed: email={credentials.email}",
                    extra={"correlation_id": correlation_id},
                )
                raise HTTPException(status_code=401, detail="Invalid credentials")
            user.pop("password_hash", None)

    token = create_jwt_token(dict(user))

    try:
        r = get_redis()
        r.setex(f"session:{token}", JWT_EXPIRY_HOURS * 3600, json.dumps(dict(user)))
    except Exception:
        pass

    logger.info(
        f"User logged in: id={user['id']} username={user['username']}",
        extra={"correlation_id": correlation_id},
    )
    return {"token": token, "user": dict(user)}


@app.get("/users/me")
def get_current_user_profile(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, username, email, full_name, role, created_at FROM users WHERE id=%s AND is_active=TRUE",
                (user["user_id"],),
            )
            db_user = cur.fetchone()
            if not db_user:
                raise HTTPException(status_code=404, detail="User not found")
            result = dict(db_user)
            result["created_at"] = str(result["created_at"])
            return result


@app.get("/users/{user_id}")
def get_user(user_id: int, user: dict = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, username, email, full_name, role, created_at FROM users WHERE id=%s AND is_active=TRUE",
                (user_id,),
            )
            db_user = cur.fetchone()
            if not db_user:
                raise HTTPException(status_code=404, detail="User not found")
            result = dict(db_user)
            result["created_at"] = str(result["created_at"])
            return result


@app.get("/users")
def list_users(user: dict = Depends(get_current_user)):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT id, username, email, full_name, role, created_at FROM users WHERE is_active=TRUE ORDER BY id"
            )
            users = [dict(r) for r in cur.fetchall()]
            for u in users:
                u["created_at"] = str(u["created_at"])
            return {"users": users, "total": len(users)}


@app.put("/users/{user_id}/role")
def update_user_role(
    user_id: int, role_update: RoleUpdate, user=Depends(require_role("super_admin"))
):
    with get_db() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "UPDATE users SET role=%s WHERE id=%s AND is_active=TRUE RETURNING id, username, email, role",
                (role_update.role, user_id),
            )
            updated = cur.fetchone()
            if not updated:
                raise HTTPException(status_code=404, detail="User not found")
            conn.commit()
            return {"message": "Role updated", "user": dict(updated)}


@app.delete("/users/{user_id}")
def delete_user(user_id: int, user: dict = Depends(get_current_user)):
    if user["role"] != "super_admin" and user["user_id"] != user_id:
        raise HTTPException(
            status_code=403, detail="Can only deactivate your own account"
        )
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
