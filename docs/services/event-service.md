# Event Service

## Overview

Manages events: creation, retrieval, updates, cancellation, and capacity tracking with atomic increment/decrement operations.

| Property | Value |
|----------|-------|
| **Port** | 8000 (internal), 8002 (dev exposed) |
| **Framework** | FastAPI |
| **Database Table** | `events` |
| **RabbitMQ Publishing** | `event.created` |
| **Dockerfile** | Multi-stage `python:3.11-slim` |

---

## Files

| File | Description |
|------|-------------|
| `main.py` | Application code: models, routes, DB schema, capacity management, RabbitMQ publisher |
| `Dockerfile` | Multi-stage build |
| `requirements.txt` | fastapi, uvicorn, psycopg2-binary, redis, pika, prometheus-fastapi-instrumentator |
| `.dockerignore` | Excludes build artifacts |

---

## Database Schema

```sql
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
);

CREATE INDEX IF NOT EXISTS idx_events_status_type ON events(status, event_type);
CREATE INDEX IF NOT EXISTS idx_events_start_date ON events(start_date);
```

---

## Endpoints

### `POST /events`

Create a new event.

**Request Body:**
```json
{
  "title": "Tech Summit",
  "description": "Annual tech conference",
  "event_type": "conference",
  "start_date": "2026-07-01 09:00:00",
  "end_date": "2026-07-03 18:00:00",
  "location": "Convention Center",
  "max_capacity": 200,
  "organizer_id": 1,
  "ticket_price": 49.99
}
```

**Response (200):**
```json
{
  "message": "Event created",
  "event": {
    "id": 1,
    "title": "Tech Summit",
    "description": "Annual tech conference",
    "event_type": "conference",
    "start_date": "2026-07-01 09:00:00",
    "end_date": "2026-07-03 18:00:00",
    "location": "Convention Center",
    "max_capacity": 200,
    "registered_count": 0,
    "organizer_id": 1,
    "ticket_price": 49.99,
    "status": "active",
    "created_at": "2026-05-10 18:10:37.179179"
  }
}
```

**Errors:**
- `400` — `end_date` must be after `start_date`

**Side Effects:**
- Publishes `event.created` to RabbitMQ
- Publishes to Redis channel `event_events`

---

### `GET /events`

List events with optional filtering.

**Query Parameters:**
- `event_type` (optional) — Filter by event type
- `status` (optional, default: `active`) — Filter by status

**Response (200):**
```json
{
  "events": [...],
  "total": 4
}
```

---

### `GET /events/{event_id}`

Get event by ID.

**Errors:**
- `404` — Event not found

---

### `PUT /events/{event_id}`

Update event fields.

**Request Body:**
```json
{
  "title": "Updated Title",
  "description": "Updated description",
  "max_capacity": 300
}
```

---

### `PATCH /events/{event_id}/increment-registration`

Atomically increment `registered_count`. Fails if event is full.

**Response (200):**
```json
{"id": 1, "registered_count": 101, "max_capacity": 200}
```

**Errors:**
- `409` — Event full or not found

**Used by:** Registration service (called synchronously via httpx)

---

### `PATCH /events/{event_id}/decrement-registration`

Atomically decrement `registered_count` (floor at 0). Used as a compensating transaction when registration fails.

**Response (200):**
```json
{"id": 1, "registered_count": 100, "max_capacity": 200}
```

---

### `DELETE /events/{event_id}`

Cancel event (sets `status='cancelled'`).

---

### `GET /health`

```json
{"status": "healthy", "service": "event-service"}
```

---

## Capacity Management

The increment/decrement endpoints are atomic SQL operations:

```sql
-- Increment (fails if full)
UPDATE events SET registered_count = registered_count + 1
WHERE id=%s AND registered_count < max_capacity
RETURNING id, registered_count, max_capacity;

-- Decrement (compensating transaction)
UPDATE events SET registered_count = GREATEST(registered_count - 1, 0)
WHERE id=%s
RETURNING id, registered_count, max_capacity;
```

This prevents race conditions where multiple users register simultaneously.

---

## Dependencies

```
fastapi
uvicorn[standard]
psycopg2-binary
redis
pika
prometheus-fastapi-instrumentator
```
