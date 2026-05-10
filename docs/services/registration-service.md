# Registration Service

## Overview

Handles event registrations with payment processing, capacity verification, and compensating transactions on failure.

| Property | Value |
|----------|-------|
| **Port** | 8000 (internal), 8003 (dev exposed) |
| **Framework** | FastAPI |
| **Database Table** | `registrations` |
| **RabbitMQ Publishing** | `registration.confirmed`, `registration.cancelled` |
| **Sync HTTP Calls** | Calls event-service for capacity management |
| **Dockerfile** | Multi-stage `python:3.11-slim` |

---

## Files

| File | Description |
|------|-------------|
| `main.py` | Application code: payment processing, registration flow, capacity orchestration |
| `Dockerfile` | Multi-stage build |
| `requirements.txt` | fastapi, uvicorn, psycopg2-binary, redis, pika, httpx, prometheus-fastapi-instrumentator |
| `.dockerignore` | Excludes build artifacts |

---

## Database Schema

```sql
CREATE TABLE IF NOT EXISTS registrations (
    id SERIAL PRIMARY KEY,
    user_id INT NOT NULL,
    event_id INT NOT NULL,
    registration_date TIMESTAMP DEFAULT NOW(),
    status VARCHAR(20) DEFAULT 'confirmed',
    payment_method VARCHAR(50) DEFAULT 'free',
    payment_status VARCHAR(20) DEFAULT 'pending',
    payment_reference VARCHAR(100),
    payment_gateway VARCHAR(50),
    payment_processed_at TIMESTAMP,
    ticket_number VARCHAR(20) UNIQUE,
    notes TEXT,
    UNIQUE(user_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_reg_user ON registrations(user_id);
CREATE INDEX IF NOT EXISTS idx_reg_event_status ON registrations(event_id, status);
```

---

## Endpoints

### `POST /registrations`

Register a user for an event with payment processing.

**Request Body:**
```json
{
  "user_id": 1,
  "event_id": 2,
  "payment_method": "card",
  "notes": null
}
```

**Response (200):**
```json
{
  "message": "Registration successful",
  "registration": {
    "id": 5,
    "user_id": 1,
    "event_id": 2,
    "registration_date": "2026-05-10 19:01:53.269171",
    "status": "confirmed",
    "payment_method": "card",
    "payment_status": "paid",
    "ticket_number": "TKT-0005-MG98S2",
    "notes": null,
    "payment_reference": "TXN-D3835F77A60F011E",
    "payment_gateway": "simulated-card",
    "payment_processed_at": "2026-05-10 19:01:53.269171"
  }
}
```

**Errors:**
- `404` — Event not found
- `409` — Event is full / User already registered
- `402` — Payment failed
- `503` — Event service unavailable

**Registration Flow:**
1. `GET /events/{id}` — Verify event exists
2. `PATCH /events/{id}/increment-registration` — Atomically reserve a spot
3. `process_payment_mock()` — Process payment
4. If payment fails → `PATCH /events/{id}/decrement-registration` (compensating transaction)
5. If payment succeeds → `INSERT INTO registrations`
6. Generate ticket number (`TKT-{id:04d}-{random}`)
7. Publish `registration.confirmed` to RabbitMQ

---

### `GET /registrations`

List all registrations (most recent first, limit 100).

---

### `GET /registrations/{id}`

Get registration by ID.

**Errors:**
- `404` — Registration not found

---

### `GET /registrations/user/{user_id}`

List all registrations for a specific user (newest first).

---

### `GET /registrations/event/{event_id}`

List confirmed registrations for a specific event.

---

### `PATCH /registrations/{id}/payment`

Update payment status.

**Request Body:**
```json
{"payment_status": "paid"}
```

---

### `POST /registrations/{id}/process-payment`

Retry payment processing for an existing registration.

**Request Body:**
```json
{
  "payment_method": "card",
  "amount": 49.99,
  "force_decline": false
}
```

---

### `DELETE /registrations/{id}`

Cancel a registration. Calls event-service to decrement capacity.

**Response (200):**
```json
{"message": "Registration cancelled"}
```

**Side Effects:**
- `PATCH /events/{id}/decrement-registration` on event-service
- Publishes `registration.cancelled` to RabbitMQ

---

### `GET /health`

```json
{"status": "healthy", "service": "registration-service"}
```

---

## Payment Processing

The `process_payment_mock()` function simulates a payment gateway:

| Method | Success Rate | Reference Format | Gateway |
|--------|-------------|-----------------|---------|
| `free` | 100% | `FREE-XXXXXXXX` | `simulated-free` |
| `card` / `credit_card` | 95% | `TXN-XXXXXXXXXXXXXXXX` | `simulated-card` |
| `paypal` | 95% | `TXN-XXXXXXXXXXXXXXXX` | `simulated-paypal` |
| `bank_transfer` | 95% | `TXN-XXXXXXXXXXXXXXXX` | `simulated-bank_transfer` |

Declined payments return reference format `DECLINED-XXXXXXXX`.

---

## Ticket Number Format

`TKT-{registration_id:04d}-{random_6_chars}`

Example: `TKT-0005-MG98S2`

---

## Dependencies

```
fastapi
uvicorn[standard]
psycopg2-binary
redis
pika
httpx
prometheus-fastapi-instrumentator
```
