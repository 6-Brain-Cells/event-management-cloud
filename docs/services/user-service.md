# User Service

## Overview

Manages user accounts: registration, authentication, profile retrieval, and soft-deletion.

| Property | Value |
|----------|-------|
| **Port** | 8000 (internal), 8001 (dev exposed) |
| **Framework** | FastAPI |
| **Database Table** | `users` |
| **RabbitMQ Publishing** | `user.registered` |
| **Dockerfile** | Multi-stage `python:3.11-slim` |

---

## Files

| File | Description |
|------|-------------|
| `main.py` | Application code: models, routes, DB schema, RabbitMQ publisher, Redis client |
| `Dockerfile` | Multi-stage build: builder + runtime with non-root user |
| `requirements.txt` | fastapi, uvicorn, psycopg2-binary, redis, pika, bcrypt, prometheus-fastapi-instrumentator |
| `.dockerignore` | Excludes `__pycache__`, `.venv`, `.git`, `__pycache__` |

---

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash VARCHAR(200) NOT NULL,
    full_name VARCHAR(100),
    created_at TIMESTAMP DEFAULT NOW(),
    is_active BOOLEAN DEFAULT TRUE
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE is_active=TRUE;
```

---

## Endpoints

### `POST /users/register`

Register a new user.

**Request Body:**
```json
{
  "username": "alice",
  "email": "alice@test.com",
  "password": "Password123",
  "full_name": "Alice Smith"
}
```

**Response (201):**
```json
{
  "message": "User registered successfully",
  "user": {
    "id": 1,
    "username": "alice",
    "email": "alice@test.com",
    "full_name": "Alice Smith",
    "created_at": "2026-05-10 18:15:57.750469"
  }
}
```

**Errors:**
- `400` — Username or email already exists

**Side Effects:**
- Publishes `user.registered` to RabbitMQ → notification-service creates welcome notification
- Publishes to Redis channel `user_events`

---

### `POST /users/login`

Authenticate and receive a token.

**Request Body:**
```json
{
  "email": "alice@test.com",
  "password": "Password123"
}
```

**Response (200):**
```json
{
  "token": "b844eb974af8731d...",
  "user": {
    "id": 1,
    "username": "alice",
    "email": "alice@test.com",
    "full_name": "Alice Smith"
  }
}
```

**Errors:**
- `401` — Invalid credentials

**Notes:**
- Token is stored in Redis with 24h TTL (`token:<hex>`)
- Password verified using bcrypt

---

### `GET /users`

List all active users.

**Response (200):**
```json
{
  "users": [
    {"id": 1, "username": "alice", "email": "alice@test.com", "full_name": "Alice Smith", "created_at": "..."}
  ],
  "total": 1
}
```

---

### `GET /users/{user_id}`

Get a specific user by ID.

**Response (200):**
```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@test.com",
  "full_name": "Alice Smith",
  "created_at": "2026-05-10 18:15:57.750469"
}
```

**Errors:**
- `404` — User not found or deactivated

---

### `DELETE /users/{user_id}`

Soft-delete a user (sets `is_active=FALSE`).

**Response (200):**
```json
{"message": "User deactivated"}
```

**Errors:**
- `404` — User not found or already deactivated

---

### `GET /health`

```json
{"status": "healthy", "service": "user-service"}
```

---

## Dependencies

```
fastapi
uvicorn[standard]
psycopg2-binary
redis
pika
bcrypt
prometheus-fastapi-instrumentator
```
