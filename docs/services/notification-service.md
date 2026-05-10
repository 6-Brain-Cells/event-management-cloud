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

## Endpoints

### `POST /notifications`

Create a single notification.

**Request Body:**
```json
{
  "user_id": 1,
  "title": "Welcome!",
  "message": "Welcome Alice! Your account has been created.",
  "notification_type": "info"
}
```

---

### `GET /notifications/user/{user_id}`

List all notifications for a user.

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

Mark a notification as read.

**Response (200):**
```json
{"message": "Marked as read"}
```

---

### `POST /notifications/broadcast`

Send the same notification to multiple users using a single bulk INSERT query.

**Request Body:**
```json
{
  "user_ids": [1, 2, 3],
  "title": "System Update",
  "message": "Maintenance scheduled for tonight",
  "notification_type": "info"
}
```

**Performance:** Uses `psycopg2.extras.execute_values` (mogrify) for a single INSERT instead of N individual queries.

---

### `GET /health`

```json
{"status": "healthy", "service": "notification-service"}
```

---

## RabbitMQ Consumer

The notification service runs a background thread that consumes messages from `notification_queue`.

### Queue Configuration

```
Exchange: "events" (type: topic, durable)
Queue: "notification_queue" (durable)
Bindings:
  - user.registered
  - event.created
  - registration.confirmed
  - registration.cancelled
```

### Message Processing

| Routing Key | Notification Title | Type |
|-------------|-------------------|------|
| `user.registered` | "Welcome!" | `info` |
| `event.created` | (no notification created) | — |
| `registration.confirmed` | "Registration Confirmed" | `confirmation` |
| `registration.cancelled` | "Registration Cancelled" | `info` |

### Consumer Thread

```python
def _consume_rabbitmq():
    params = pika.ConnectionParameters(...)
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.exchange_declare(exchange="events", exchange_type="topic", durable=True)
    channel.queue_declare(queue="notification_queue", durable=True)
    for key in ["user.registered", "event.created", "registration.confirmed", "registration.cancelled"]:
        channel.queue_bind(queue="notification_queue", exchange="events", routing_key=key)
    channel.basic_consume(queue="notification_queue", on_message_callback=_on_message, auto_ack=False)
    channel.start_consuming()
```

The consumer runs in a daemon thread started during the FastAPI `startup` event.

---

## Dependencies

```
fastapi
uvicorn[standard]
psycopg2-binary
pika
prometheus-fastapi-instrumentator
```
