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
| **Auth** | JWT (user_id from token, not request body) |

---

## Files

| File | Description |
|------|-------------|
| `main.py` | Application code: payment processing, registration flow, capacity orchestration |
| `Dockerfile` | Multi-stage build |
| `requirements.txt` | fastapi, uvicorn, psycopg2-binary, redis, pika, httpx, alembic, sqlalchemy, prometheus-fastapi-instrumentator |
| `alembic.ini` | Alembic configuration (version_table: `alembic_version_registration`) |
| `alembic/env.py` | Migration environment with service-specific version table |
| `alembic/versions/001_create_registrations_table.py` | Initial migration: creates registrations table and indexes |
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

## Authentication & Authorization

| Endpoint Group | Required Role | Notes |
|---------------|---------------|-------|
| `POST /registrations` | attendee, organizer, super_admin | user_id derived from JWT, not request body |
| `GET /registrations` | Any user (own only), super_admin (all) | Scoped to requesting user |
| `GET /registrations/{id}` | Own user or super_admin | — |
| `GET /registrations/user/{user_id}` | Own user or super_admin | — |
| `GET /registrations/event/{event_id}` | Any authenticated user | — |
| `PATCH /registrations/{id}/payment` | super_admin | — |
| `POST /registrations/{id}/process-payment` | Own user or super_admin | — |
| `DELETE /registrations/{id}` | Own user or super_admin | Sends X-Service-Key to event-service |

---

## Endpoints

### `POST /registrations`

Register a user for an event with payment processing. `user_id` is derived from the JWT token, not the request body.

**Request Body:**
```json
{
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
1. `GET /events/{id}` — Verify event exists (includes `X-Service-Key` header)
2. `PATCH /events/{id}/increment-registration` — Atomically reserve a spot (includes `X-Service-Key` header)
3. `process_payment_mock()` — Process payment
4. If payment fails → `PATCH /events/{id}/decrement-registration` (compensating transaction, includes `X-Service-Key` header)
5. If payment succeeds → `INSERT INTO registrations`
6. Generate ticket number (`TKT-{id:04d}-{random}`)
7. Publish `registration.confirmed` to RabbitMQ

---

### `GET /registrations`

List registrations with pagination (most recent first).

**Query Parameters:**
- `page` (optional, default: `1`) — Page number (1-indexed)
- `page_size` (optional, default: `20`, max: `100`) — Items per page

**Response (200):**
```json
{
  "registrations": [...],
  "total": 15,
  "page": 1,
  "page_size": 20,
  "total_pages": 1
}
```

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
- `PATCH /events/{id}/decrement-registration` on event-service (includes `X-Service-Key` header)
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

## Database Migrations

The registration service uses **Alembic** for database schema migrations. On startup, the `startup()` function attempts to run `alembic upgrade head` first. If Alembic fails, it falls back to executing `CREATE TABLE IF NOT EXISTS` SQL directly.

### Migration Chain

| Version | File | Description |
|---------|------|-------------|
| `001_registrations` | `alembic/versions/001_create_registrations_table.py` | Creates `registrations` table and indexes |

### Version Table

Alembic tracks applied migrations in `alembic_version_registration` (not the default `alembic_version`) to avoid conflicts with other services sharing the same PostgreSQL database.

---

## Connection Pool Configuration

The registration service uses configurable connection pool settings via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_POOL_MIN` | `2` | Minimum connections kept open |
| `DB_POOL_MAX` | `10` | Maximum connections allowed |
| `DB_CONNECT_TIMEOUT` | `5` | Connection timeout in seconds |

All pool connections use `statement_timeout=5000ms` to prevent long-running queries from blocking the pool.

---

## Dependencies

```
fastapi
uvicorn[standard]
psycopg2-binary
redis
pika
httpx
PyJWT>=2.8.0
alembic>=1.13.0
sqlalchemy>=2.0.0
prometheus-fastapi-instrumentator
```
