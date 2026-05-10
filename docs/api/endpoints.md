# API Reference — Complete Endpoint Documentation

All endpoints are accessed through the nginx gateway at `http://localhost:8080/api/`.

---

## User Service

### `POST /api/users/register`

Register a new user account.

```bash
curl -X POST http://localhost:8080/api/users/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "alice",
    "email": "alice@test.com",
    "password": "Password123",
    "full_name": "Alice Smith"
  }'
```

**Request Body:**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| username | string | yes | Unique, max 50 chars |
| email | string | yes | Unique, valid email, max 100 chars |
| password | string | yes | Hashed with bcrypt (12 rounds) |
| full_name | string | yes | Max 100 chars |

**Response (200):**
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
| Status | Detail |
|--------|--------|
| 400 | Username or email already exists |

---

### `POST /api/users/login`

Authenticate user and receive token.

```bash
curl -X POST http://localhost:8080/api/users/login \
  -H "Content-Type: application/json" \
  -d '{"email": "alice@test.com", "password": "Password123"}'
```

**Response (200):**
```json
{
  "token": "b844eb974af8731d7782132cecc02337...",
  "user": {
    "id": 1,
    "username": "alice",
    "email": "alice@test.com",
    "full_name": "Alice Smith"
  }
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 401 | Invalid credentials |

---

### `GET /api/users`

List all active users.

```bash
curl http://localhost:8080/api/users
```

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

### `GET /api/users/{user_id}`

Get user by ID.

```bash
curl http://localhost:8080/api/users/1
```

**Errors:**
| Status | Detail |
|--------|--------|
| 404 | User not found |

---

### `DELETE /api/users/{user_id}`

Soft-delete a user (deactivate).

```bash
curl -X DELETE http://localhost:8080/api/users/1
```

**Response (200):** `{"message": "User deactivated"}`

**Errors:**
| Status | Detail |
|--------|--------|
| 404 | User not found |

---

## Event Service

### `POST /api/events`

Create a new event.

```bash
curl -X POST http://localhost:8080/api/events \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Tech Summit",
    "description": "Annual tech conference",
    "event_type": "conference",
    "start_date": "2026-07-01 09:00:00",
    "end_date": "2026-07-03 18:00:00",
    "location": "Convention Center",
    "max_capacity": 200,
    "organizer_id": 1,
    "ticket_price": 49.99
  }'
```

**Request Body:**

| Field | Type | Required | Default |
|-------|------|----------|---------|
| title | string | yes | — |
| description | string | yes | — |
| event_type | string | yes | — |
| start_date | string (ISO) | yes | — |
| end_date | string (ISO) | yes | — |
| location | string | yes | — |
| max_capacity | int | yes | 100 |
| organizer_id | int | yes | — |
| ticket_price | float | no | 0.0 |

**Response (200):**
```json
{
  "message": "Event created",
  "event": {
    "id": 1, "title": "Tech Summit", "status": "active",
    "registered_count": 0, "max_capacity": 200, "ticket_price": 49.99, ...
  }
}
```

---

### `GET /api/events`

List events with optional filters.

```bash
curl http://localhost:8080/api/events
curl http://localhost:8080/api/events?event_type=conference&status=active
```

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| event_type | string | — | Filter by type |
| status | string | `active` | Filter by status |

---

### `GET /api/events/{event_id}`

Get event by ID.

```bash
curl http://localhost:8080/api/events/1
```

---

### `PUT /api/events/{event_id}`

Update event fields.

```bash
curl -X PUT http://localhost:8080/api/events/1 \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated Title", "max_capacity": 300}'
```

---

### `DELETE /api/events/{event_id}`

Cancel an event.

```bash
curl -X DELETE http://localhost:8080/api/events/1
```

---

## Registration Service

### `POST /api/registrations`

Register for an event with payment processing.

```bash
curl -X POST http://localhost:8080/api/registrations \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "event_id": 2, "payment_method": "card"}'
```

**Request Body:**

| Field | Type | Required | Default | Values |
|-------|------|----------|---------|--------|
| user_id | int | yes | — | — |
| event_id | int | yes | — | — |
| payment_method | string | no | `"free"` | `free`, `card`, `credit_card`, `paypal`, `bank_transfer` |
| notes | string | no | `null` | — |

**Response (200):**
```json
{
  "message": "Registration successful",
  "registration": {
    "id": 5,
    "user_id": 1,
    "event_id": 2,
    "status": "confirmed",
    "payment_method": "card",
    "payment_status": "paid",
    "ticket_number": "TKT-0005-MG98S2",
    "payment_reference": "TXN-D3835F77A60F011E",
    "payment_gateway": "simulated-card",
    "payment_processed_at": "2026-05-10 19:01:53.269171"
  }
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 404 | Event not found |
| 409 | Event is full / User already registered |
| 402 | Payment failed |
| 503 | Event service unavailable |

---

### `GET /api/registrations`

List all registrations (limit 100).

```bash
curl http://localhost:8080/api/registrations
```

---

### `GET /api/registrations/{id}`

Get registration by ID.

---

### `GET /api/registrations/user/{user_id}`

List registrations for a user.

```bash
curl http://localhost:8080/api/registrations/user/1
```

---

### `GET /api/registrations/event/{event_id}`

List confirmed registrations for an event.

```bash
curl http://localhost:8080/api/registrations/event/1
```

---

### `DELETE /api/registrations/{id}`

Cancel a registration (restores event capacity).

```bash
curl -X DELETE http://localhost:8080/api/registrations/5
```

**Response (200):** `{"message": "Registration cancelled"}`

---

## Notification Service

### `GET /api/notifications/user/{user_id}`

List notifications for a user.

```bash
curl http://localhost:8080/api/notifications/user/1
```

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

### `PATCH /api/notifications/{id}/read`

Mark notification as read.

```bash
curl -X PATCH http://localhost:8080/api/notifications/1/read
```

**Response (200):** `{"message": "Marked as read"}`

---

### `POST /api/notifications/broadcast`

Send notification to multiple users.

```bash
curl -X POST http://localhost:8080/api/notifications/broadcast \
  -H "Content-Type: application/json" \
  -d '{"user_ids": [1, 2, 3], "title": "System Update", "message": "Maintenance tonight", "notification_type": "info"}'
```

---

## Health Endpoints

All services expose a health endpoint directly (bypassing nginx):

```bash
curl http://localhost:8001/health  # user-service
curl http://localhost:8002/health  # event-service
curl http://localhost:8003/health  # registration-service
curl http://localhost:8004/health  # notification-service
curl http://localhost:8080/health  # nginx gateway
```

All return: `{"status": "healthy", "service": "<name>"}` (or `gateway-healthy` for nginx)

---

## Metrics Endpoints

All services expose Prometheus metrics:

```bash
curl http://localhost:8001/metrics  # user-service
curl http://localhost:8002/metrics  # event-service
curl http://localhost:8003/metrics  # registration-service
curl http://localhost:8004/metrics  # notification-service
```

Metrics include: `http_requests_total`, `http_request_duration_seconds`, `http_request_size_bytes`, `http_response_size_bytes`, Python runtime metrics.
