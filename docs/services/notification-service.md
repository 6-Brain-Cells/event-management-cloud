# Notification Service

## Overview

Consumes events from RabbitMQ and creates user notifications. Also provides REST endpoints for notification management and bulk broadcasting.

| Property | Value |
|----------|-------|
| **Port** | 8000 (internal), 8004 (dev exposed) |
| **Framework** | FastAPI |
| **Database Table** | `notifications` |
| **RabbitMQ Consuming** | `notification_queue` bound to all routing keys on `events` exchange |
| **Dockerfile** | Multi-stage `python:3.11-slim` |
| **Auth** | JWT (scoped to own user; super_admin has full access) |

---

## Files

| File | Description |
|------|-------------|
| `main.py` | Application code: RabbitMQ consumer thread, notification CRUD, broadcast |
| `Dockerfile` | Multi-stage build |
| `requirements.txt` | fastapi, uvicorn, psycopg2-binary, pika, prometheus-fastapi-instrumentator |
| `.dockerignore` | Excludes build artifacts |

**Note:** This service does NOT include `redis` in its requirements. It only consumes from RabbitMQ to prevent duplicate notifications.

---

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS notifications (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    title VARCHAR(200) NOT NULL,
    message TEXT,
    notification_type VARCHAR(50) DEFAULT 'info',
    is_read BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notifications_user_read ON notifications(user_id, is_read);
```

---

## Authentication & Authorization

| Endpoint Group | Required Role | Notes |
|---------------|---------------|-------|
| `POST /notifications` | super_admin | — |
| `GET /notifications/user/{user_id}` | Own user or super_admin | Scoped to requesting user |
| `PATCH /notifications/{id}/read` | Own user or super_admin | Ownership verified before marking read |
| `POST /notifications/broadcast` | super_admin | — |

---

## Endpoints

### `POST /notifications`

Create a single notification. super_admin only.

**Requires:** Bearer token (super_admin)

**Request Body:**
```json
{
  "user_id": 1,
  "title": "Welcome!",
  "message": "Welcome Alice! Your account has been created.",
  "notification_type": "info"
}
```

**Response (200):**
```json
{
  "message": "Notification sent",
  "notification": {
    "id": 1,
    "user_id": 1,
    "title": "Welcome!",
    "message": "Welcome Alice! Your account has been created.",
    "notification_type": "info",
    "is_read": false,
    "created_at": "2026-05-10 18:15:57.788032"
  }
}
```

---

### `GET /notifications/user/{user_id}`

List all notifications for a user. Users can only view their own notifications; super_admin can view any.

**Requires:** Bearer token (own user or super_admin)

**Query Parameters:**
- `unread_only` (optional, boolean, default: false) — Only return unread notifications

**Response (200):**
```json
{
  "notifications": [
    {
      "id": 1,
      "user_id": 1,
      "title": "Welcome!",
      "message": "Welcome Alice! Your account has been created.",
      "notification_type": "info",
      "is_read": false,
      "created_at": "2026-05-10 18:15:57.788032"
    }
  ],
  "total": 1
}
```

---

### `PATCH /notifications/{notification_id}/read`

Mark a notification as read. Ownership verified before marking read.

**Requires:** Bearer token (own user or super_admin)

**Response (200):**
```json
{"message": "Marked as read"}
```

**Errors:**
- `404` — Notification not found

---

### `POST /notifications/broadcast`

Send the same notification to multiple users using a single bulk INSERT query. super_admin only.

**Requires:** Bearer token (super_admin)

**Request Body:**
```json
{
  "user_ids": [1, 2, 3],
  "title": "System Update",
  "message": "Maintenance scheduled for tonight"
}
```

**Response (200):**
```json
{"message": "Broadcast sent to 3 users"}
```

**Performance:** Uses `psycopg2` `cur.mogrify()` for efficient batch INSERT instead of N individual queries.

---

### `GET /health`

```json
{"status": "healthy", "service": "notification-service"}
```

---

## RabbitMQ Consumer

The notification service runs a background daemon thread that consumes messages from `notification_queue`.

### Queue Configuration

```
Exchange: "events" (type: topic, durable)
Queue: "notification_queue" (durable)
Bindings:
  - user.registered
  - event.created
  - registration.confirmed
  - registration.cancelled
Prefetch: 10 messages
```

### Message Processing

| Routing Key | Event Type | Action | Notification Type |
|-------------|-----------|--------|-------------------|
| `user.registered` | `user_registered` | Creates "Welcome!" notification for the user | `info` |
| `event.created` | `event_created` | Logs event title to console (no DB notification) | — |
| `registration.confirmed` | `registration_confirmed` | Creates "Registration Confirmed" notification with ticket number | `confirmation` |
| `registration.cancelled` | `registration_cancelled` | Logs cancellation to console (no DB notification) | — |

### Message Acknowledgment

- **Success:** `basic_ack` after processing — message is removed from queue
- **Failure:** `basic_nack` with `requeue=True` — message goes back to queue for retry
- This ensures no notifications are lost if the service crashes mid-processing

### Consumer Thread

```python
def rabbitmq_consumer():
    params = pika.ConnectionParameters(
        heartbeat=600,
        blocked_connection_timeout=300,
    )
    conn = pika.BlockingConnection(params)
    ch = conn.channel()
    ch.exchange_declare(exchange="events", exchange_type="topic", durable=True)
    result = ch.queue_declare(queue="notification_queue", durable=True)
    for key in ["user.registered", "event.created", "registration.confirmed", "registration.cancelled"]:
        ch.queue_bind(exchange="events", queue=result.method.queue, routing_key=key)
    ch.basic_qos(prefetch_count=10)
    ch.basic_consume(queue=queue_name, on_message_callback=callback)
    ch.start_consuming()
```

The consumer runs in a daemon thread started during the FastAPI `startup` event.

---

## Dependencies

```
fastapi
uvicorn[standard]
psycopg2-binary
pika
PyJWT>=2.8.0
prometheus-fastapi-instrumentator
```
