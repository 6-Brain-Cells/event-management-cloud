# API Reference — Complete Endpoint Documentation

All endpoints are accessed through the nginx gateway at `http://localhost:8080/api/`.

## Authentication

All endpoints (except register, login, and health) require a JWT Bearer token in the `Authorization` header:

```
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

### Roles

| Role | Capabilities |
|------|-------------|
| `super_admin` | Full access: manage all users, events, registrations, notifications; assign roles |
| `organizer` | Create/update/cancel own events; register for events; view own data |
| `attendee` | Register for events; view own registrations and notifications |

### Service-to-Service Auth

Internal service calls (e.g., registration-service → event-service) use the `X-Service-Key` header instead of JWT.

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
    "full_name": "Alice Smith",
    "role": "organizer"
  }'
```

**Request Body:**

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| username | string | yes | Unique, max 50 chars |
| email | string | yes | Unique, valid email, max 100 chars |
| password | string | yes | Hashed with bcrypt (12 rounds) |
| full_name | string | yes | Max 100 chars |
| role | string | no | attendee | super_admin, organizer, attendee |

**Input Validation:**
- `username`: 3-50 characters, alphanumeric and underscores only
- `email`: Valid email format, auto-lowercased
- `password`: 8-128 characters
- `full_name`: 1-100 characters
- `role`: Must be one of `super_admin`, `organizer`, `attendee` (default: `attendee`)

**Response (201):**
```json
{
  "message": "User registered successfully",
  "user": {
    "id": 1,
    "username": "alice",
    "email": "alice@test.com",
    "full_name": "Alice Smith",
    "role": "organizer",
    "created_at": "2026-05-10 18:15:57.750469"
  }
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 400 | Username or email already exists |
| 422 | Validation error (invalid username/email/password/role format) |

**Side Effects:**
- Publishes `user.registered` to RabbitMQ → notification-service creates welcome notification
- Publishes to Redis channel `user_events`

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
  "token": "eyJhbGciOiJIUzI1NiIs...",
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

**Notes:**
- Returns a JWT token (HS256, 24h expiry) with user_id, username, email, and role claims
- Session stored in Redis with 24h TTL (`session:<jwt>`)
- Password verified using bcrypt

---

### `GET /api/users`

List all active users.

**Auth:** Any authenticated user

```bash
curl http://localhost:8080/api/users \
  -H "Authorization: Bearer $TOKEN"
```

**Response (200):**
```json
{
  "users": [
    {"id": 1, "username": "alice", "email": "alice@test.com", "full_name": "Alice Smith", "role": "organizer", "created_at": "..."}
  ],
  "total": 1
}
```

---

### `GET /api/users/me`

Get the current authenticated user's profile.

```bash
curl http://localhost:8080/api/users/me \
  -H "Authorization: Bearer $TOKEN"
```

**Auth:** Any authenticated user

**Response (200):**
```json
{
  "id": 1,
  "username": "alice",
  "email": "alice@test.com",
  "full_name": "Alice Smith",
  "role": "organizer",
  "created_at": "2026-05-10 18:15:57.750469"
}
```

---

### `GET /api/users/{user_id}`

Get user by ID.

**Auth:** Any authenticated user

```bash
curl http://localhost:8080/api/users/1 \
  -H "Authorization: Bearer $TOKEN"
```

**Errors:**
| Status | Detail |
|--------|--------|
| 404 | User not found |

---

### `PUT /api/users/{user_id}/role`

Update a user's role.

```bash
curl -X PUT http://localhost:8080/api/users/2/role \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"role": "organizer"}'
```

**Auth:** super_admin only

**Request Body:**

| Field | Type | Required | Values |
|-------|------|----------|--------|
| role | string | yes | `super_admin`, `organizer`, `attendee` |

**Response (200):**
```json
{
  "message": "Role updated",
  "user": {
    "id": 2,
    "username": "bob",
    "email": "bob@test.com",
    "role": "organizer"
  }
}
```

**Errors:**
| Status | Detail |
|--------|--------|
| 403 | Insufficient permissions (not super_admin) |
| 404 | User not found |

---

### `DELETE /api/users/{user_id}`

Soft-delete a user (deactivate).

**Auth:** Self-deletion or super_admin

```bash
curl -X DELETE http://localhost:8080/api/users/1 \
  -H "Authorization: Bearer $TOKEN"
```

**Response (200):** `{"message": "User deactivated"}`

**Errors:**
| Status | Detail |
|--------|--------|
| 403 | Can only deactivate your own account (unless super_admin) |
| 404 | User not found |

---

## Event Service

### `POST /api/events`

Create a new event.

**Auth:** organizer or super_admin

```bash
curl -X POST http://localhost:8080/api/events \
  -H "Authorization: Bearer $TOKEN" \
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
| organizer_id | int | no | Auto-set from JWT for organizer; optional for super_admin |
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

**Side Effects:**
- Publishes `event.created` to RabbitMQ
- Publishes to Redis channel `event_events`

**Errors:**
| Status | Detail |
|--------|--------|
| 403 | Insufficient permissions (attendee cannot create events) |

---

### `GET /api/events`

List events with optional filters and pagination. Results are cached in Redis (30s TTL).

**Auth:** Any authenticated user (service key also accepted)

```bash
curl http://localhost:8080/api/events \
  -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8080/api/events?event_type=conference&status=active&page=1&page_size=20" \
  -H "Authorization: Bearer $TOKEN"
```

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| event_type | string | — | Filter by type |
| status | string | `active` | Filter by status (`super_admin` can use `all` to see cancelled events) |
| page | int | `1` | Page number (1-indexed) |
| page_size | int | `20` | Items per page (max 100) |

**Response (200):**
```json
{
  "events": [...],
  "total": 42,
  "page": 1,
  "page_size": 20,
  "total_pages": 3
}
```

---

### `GET /api/events/{event_id}`

Get event by ID.

**Auth:** Any authenticated user

```bash
curl http://localhost:8080/api/events/1 \
  -H "Authorization: Bearer $TOKEN"
```

---

### `PUT /api/events/{event_id}`

Update event fields. Requires optimistic concurrency via `version` field.

**Auth:** organizer (own events only) or super_admin

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| title | string | no | New title |
| description | string | no | New description |
| location | string | no | New location |
| max_capacity | int | no | New capacity |
| ticket_price | float | no | New price |
| version | int | **yes** | Current version of the event (for optimistic concurrency) |

```bash
curl -X PUT http://localhost:8080/api/events/1 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated Title", "max_capacity": 300, "version": 1}'
```

**Errors:**
| Status | Detail |
|--------|--------|
| 403 | Insufficient permissions (not the event owner or super_admin) |
| 409 | Optimistic concurrency conflict (version mismatch). Returns `{"message": "...", "current_version": N, "provided_version": M}` |

---

### `DELETE /api/events/{event_id}`

Cancel an event. Requires optimistic concurrency via `version` query parameter.

**Auth:** organizer (own events only) or super_admin

**Query Parameters:**

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| version | int | **yes** | Current version of the event (for optimistic concurrency) |

```bash
curl -X DELETE "http://localhost:8080/api/events/1?version=2" \
  -H "Authorization: Bearer $TOKEN"
```

**Errors:**
| Status | Detail |
|--------|--------|
| 403 | Insufficient permissions (not the event owner or super_admin) |
| 409 | Optimistic concurrency conflict (version mismatch). Returns `{"message": "...", "current_version": N, "provided_version": M}` |

---

## Registration Service

### `POST /api/registrations`

Register for an event with payment processing.

**Auth:** attendee, organizer, or super_admin. user_id is derived from the JWT token.

```bash
curl -X POST http://localhost:8080/api/registrations \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"event_id": 1, "payment_method": "card"}'
```

**Request Body:**

| Field | Type | Required | Default | Values |
|-------|------|----------|---------|--------|
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

**Registration Flow:**
1. `GET /events/{id}` — Verify event exists (via `X-Service-Key`)
2. `PATCH /events/{id}/increment-registration` — Atomically reserve a spot
3. `process_payment_mock()` — Process payment
4. If payment fails → `PATCH /events/{id}/decrement-registration` (compensating transaction)
5. If payment succeeds → `INSERT INTO registrations`
6. Generate ticket number (`TKT-{id:04d}-{random}`)
7. Publish `registration.confirmed` to RabbitMQ

---

### `GET /api/registrations`

List registrations with pagination.

**Auth:** Any user (scoped to own; super_admin sees all)

```bash
curl http://localhost:8080/api/registrations \
  -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8080/api/registrations?page=2&page_size=10" \
  -H "Authorization: Bearer $TOKEN"
```

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| page | int | `1` | Page number (1-indexed) |
| page_size | int | `20` | Items per page (max 100) |

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

### `GET /api/registrations/{id}`

Get registration by ID.

**Auth:** Own user or super_admin

**Errors:**
| Status | Detail |
|--------|--------|
| 403 | Insufficient permissions (not the registration owner or super_admin) |

---

### `GET /api/registrations/user/{user_id}`

List registrations for a user.

**Auth:** Own user or super_admin

```bash
curl http://localhost:8080/api/registrations/user/1 \
  -H "Authorization: Bearer $TOKEN"
```

**Errors:**
| Status | Detail |
|--------|--------|
| 403 | Insufficient permissions (not the user or super_admin) |

---

### `GET /api/registrations/event/{event_id}`

List confirmed registrations for an event.

```bash
curl http://localhost:8080/api/registrations/event/1
```

---

### `PATCH /api/registrations/{id}/payment`

Update payment status.

**Auth:** super_admin only

```bash
curl -X PATCH http://localhost:8080/api/registrations/5/payment \
  -H "Content-Type: application/json" \
  -d '{"payment_status": "paid"}'
```

**Response (200):**
```json
{
  "message": "Payment status updated",
  "registration": {"id": 5, "payment_status": "paid"}
}
```

---

### `POST /api/registrations/{id}/process-payment`

Retry payment processing for an existing registration.

**Auth:** Own user or super_admin

```bash
curl -X POST http://localhost:8080/api/registrations/5/process-payment \
  -H "Content-Type: application/json" \
  -d '{"payment_method": "card", "amount": 49.99, "force_decline": false}'
```

**Request Body:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| payment_method | string | yes | `free`, `card`, `credit_card`, `paypal`, `bank_transfer` |
| amount | float | yes | Payment amount |
| force_decline | boolean | no | Force payment decline for testing (default: false) |

**Response (200):**
```json
{
  "message": "Payment processed",
  "payment": {
    "id": 5,
    "payment_method": "card",
    "payment_status": "paid",
    "payment_reference": "TXN-A1B2C3D4E5F6G7H8",
    "payment_gateway": "simulated-card",
    "payment_processed_at": "2026-05-10 19:30:00.123456"
  }
}
```

---

### `DELETE /api/registrations/{id}`

Cancel a registration (restores event capacity).

**Auth:** Own user or super_admin

```bash
curl -X DELETE http://localhost:8080/api/registrations/5 \
  -H "Authorization: Bearer $TOKEN"
```

**Response (200):** `{"message": "Registration cancelled"}`

**Side Effects:**
- `PATCH /events/{id}/decrement-registration` on event-service
- Publishes `registration.cancelled` to RabbitMQ

---

## Notification Service

### `GET /api/notifications/user/{user_id}`

List notifications for a user.

**Auth:** Own user or super_admin

```bash
curl http://localhost:8080/api/notifications/user/1 \
  -H "Authorization: Bearer $TOKEN"
```

**Query Parameters:**

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| unread_only | boolean | false | Only return unread notifications |

**Errors:**
| Status | Detail |
|--------|--------|
| 403 | Insufficient permissions (not the user or super_admin) |

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

### `POST /api/notifications`

Create a single notification.

**Auth:** super_admin only

```bash
curl -X POST http://localhost:8080/api/notifications \
  -H "Content-Type: application/json" \
  -d '{"user_id": 1, "title": "Alert", "message": "Test notification", "notification_type": "info"}'
```

---

### `PATCH /api/notifications/{id}/read`

Mark notification as read.

**Auth:** Own user or super_admin

```bash
curl -X PATCH http://localhost:8080/api/notifications/1/read \
  -H "Authorization: Bearer $TOKEN"
```

**Response (200):** `{"message": "Marked as read"}`

---

### `POST /api/notifications/broadcast`

Send notification to multiple users.

**Auth:** super_admin only

```bash
curl -X POST http://localhost:8080/api/notifications/broadcast \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_ids": [1, 2, 3], "title": "System Update", "message": "Maintenance tonight"}'
```

---

## Redis Caching

Event listing responses (`GET /api/events`) are cached in Redis to reduce database load under high traffic.

**Behavior:**
- **TTL:** 30 seconds (configurable via `CACHE_TTL` env var)
- **Cache key format:** `events:list:{status}:{event_type}:{page}:{page_size}`
- **Cache population:** On first request for a given filter combination, the DB result is stored in Redis
- **Cache invalidation:** Cache is cleared on any event create, update, or delete operation
- **Fallback:** If Redis is unavailable, the endpoint queries the database directly (graceful degradation)

---

## Health Endpoints

### Via nginx gateway

```bash
curl http://localhost:8080/health                      # gateway
curl http://localhost:8080/api/users/health             # user-service
curl http://localhost:8080/api/events/health            # event-service
curl http://localhost:8080/api/registrations/health     # registration-service
curl http://localhost:8080/api/notifications/health     # notification-service
```

Gateway returns: `{"status":"gateway-healthy"}`
Services return: `{"status":"healthy","service":"<name>"}`

### Direct service access (dev only)

```bash
curl http://localhost:8001/health  # user-service
curl http://localhost:8002/health  # event-service
curl http://localhost:8003/health  # registration-service
curl http://localhost:8004/health  # notification-service
```

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
