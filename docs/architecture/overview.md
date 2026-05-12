# Architecture Overview

## Table of Contents

- [Architecture Style](#architecture-style)
- [System Topology](#system-topology)
- [Communication Patterns](#communication-patterns)
- [Data Flow Diagrams](#data-flow-diagrams)
- [Cross-cutting Concerns](#cross-cutting-concerns)
- [Container Architecture](#container-architecture)
- [Technology Stack](#technology-stack)

---

## Architecture Style

**Microservices Architecture** with **API Gateway** pattern.

Each service is a standalone FastAPI application running in its own Docker container. Services communicate via synchronous HTTP calls (for request/response) and asynchronous messaging via RabbitMQ (for event-driven flows).

### Key Principles

1. **One service per container** — each microservice has its own Dockerfile and builds independently
2. **Shared database, owned tables** — all services connect to the same PostgreSQL instance but each owns specific tables
3. **Event-driven notifications** — services publish events to RabbitMQ; notification-service consumes them
4. **API Gateway pattern** — nginx routes all external traffic, enforces rate limits
5. **Connection pooling** — `ThreadedConnectionPool(2-10)` per service for DB efficiency
6. **Graceful degradation** — Redis/RabbitMQ failures are caught silently; core functionality continues
7. **JWT-based RBAC** — All endpoints (except register/login/health) require Bearer token; roles (super_admin, organizer, attendee) enforced per endpoint
8. **Input validation** — Pydantic field validators sanitize all user inputs at the API layer

---

## System Topology

```
                          Internet / Local Client
                                   │
                                   ▼
                          ┌────────────────┐
                          │   Nginx :80    │  API Gateway
                          │  Rate Limiting  │  Reverse Proxy
                          │  Static Files   │  TLS Termination
                          └──┬─┬─┬─┬───────┘
                             │ │ │ │
               ┌─────────────┘ │ │ └─────────────┐
               ▼               ▼ ▼               ▼
        ┌────────────┐  ┌────────────┐  ┌─────────────────┐  ┌──────────────────┐
        │ User Svc   │  │ Event Svc  │  │ Registration Svc│  │ Notification Svc │
        │ :8000      │  │ :8000      │  │ :8000           │  │ :8000            │
        │ FastAPI     │  │ FastAPI     │  │ FastAPI          │  │ FastAPI           │
        └─────┬──────┘  └─────┬──────┘  └────┬────────────┘  └────┬─────────────┘
              │               │              │                     │
              │         (httpx sync)         │                     │
              │               │◄─────────────┘                     │
              │               │                                    │
              │    ┌──────────┴────────────────────────────────────┘
              │    │
              ▼    ▼
     ┌───────────────────────────────────────────────────┐
     │              RabbitMQ (AMQP :5672)                 │
     │         Exchange: "events" (topic)                 │
     │   ┌──────────────────────────────────────────┐    │
     │   │  notification_queue (consumer: notif-svc) │    │
     │   │  bindings: user.*, event.*, registration.*│    │
     │   └──────────────────────────────────────────┘    │
     └───────────────────────────────────────────────────┘
              │          │            │
              ▼          ▼            ▼
     ┌────────────┐ ┌─────────┐ ┌──────────┐
     │ PostgreSQL │ │  Redis   │ │  Nginx   │
     │ :5432      │ │ :6379    │ │ static   │
     │            │ │ pub-sub  │ │ assets   │
     └────────────┘ └─────────┘ └──────────┘
```

---

## Communication Patterns

### Synchronous (HTTP via httpx)

Used when the caller needs an immediate response to proceed. Inter-service HTTP calls include `X-Service-Key` header for authentication.

```
Registration Service ──GET /events/{id}──► Event Service
                        ◄──event data────

Registration Service ──PATCH /events/{id}/increment-registration──► Event Service
                        ◄──{id, registered_count, max_capacity}────────────────

Registration Service ──PATCH /events/{id}/decrement-registration──► Event Service
                        ◄──{id, registered_count, max_capacity}────────────────
```

### Asynchronous (RabbitMQ Topic Exchange)

Used for fire-and-forget events where the publisher doesn't need a response.

```
Publisher                    Exchange: "events" (topic)              Consumer
─────────────────────────    ──────────────────────────────    ──────────────────
User Service ──────────────► routing_key: user.registered ──► Notification Svc
Event Service ─────────────► routing_key: event.created ────► Notification Svc
Registration Service ──────► routing_key: registration.confirmed ► Notification Svc
Registration Service ──────► routing_key: registration.cancelled ► Notification Svc
```

### Cache (Redis Pub-Sub)

Secondary notification channel. Services publish to Redis channels as a backup, but notification-service only consumes from RabbitMQ to avoid duplicates.

```
User Service ──publish──► Redis channel: "user_events"
Event Service ──publish──► Redis channel: "event_events"
Registration Service ──publish──► Redis channel: "notification_events"
```

Redis is also used for JWT session storage — the user-service stores JWT sessions with 24h TTL (`session:<jwt>`).

---

## Data Flow Diagrams

### User Registration Flow

```
Client ──POST /api/users/register──► Nginx ──POST /users/register──► User Service
                                                                            │
                                                                    1. Hash password (bcrypt)
                                                                    2. INSERT INTO users
                                                                    3. COMMIT
                                                                            │
                                                                    4. Publish to Redis
                                                                    5. Publish to RabbitMQ
                                                                       routing_key: "user.registered"
                                                                            │
                                                                            ▼
                                                                    Notification Service
                                                                    6. Consume message
                                                                    7. INSERT INTO notifications
                                                                            │
Client ◄──201 { user, message }─────────────────────────────────────────────┘
```

### Event Registration Flow (with payment)

```
Client ──POST /api/registrations──► Nginx ──POST /registrations──► Registration Service
                                                                            │
                                                                    1. GET /events/{id} (httpx)
                                                                       └──► Event Service
                                                                    2. PATCH /events/{id}/increment-registration
                                                                       └──► Event Service (atomic increment)
                                                                    3. process_payment_mock()
                                                                       ├── free → always success
                                                                       └── card/paypal/bank → 95% success, 5% decline
                                                                            │
                                                                    ┌─── Payment Success ───┐
                                                                    │ 4. INSERT registration │
                                                                    │ 5. Generate ticket #   │
                                                                    │ 6. COMMIT              │
                                                                    │ 7. Publish to RabbitMQ │
                                                                    │    routing_key:        │
                                                                    │    "registration.      │
                                                                    │     confirmed"         │
                                                                    └────────────────────────┘
                                                                            │
                                                                    ┌─── Payment Failure ────┐
                                                                    │ 4. PATCH /events/{id}/  │
                                                                    │    decrement-registration│
                                                                    │    (compensating txn)    │
                                                                    │ 5. RETURN 402            │
                                                                    └─────────────────────────┘
```

### Notification Delivery Flow

```
RabbitMQ Consumer Thread (runs in notification-service)
│
├── Message arrives on "notification_queue"
│   routing_key: "user.registered"
│   body: { "event": "user_registered", "user_id": 1, ... }
│
├── Parse message
├── Determine action from event type
│   ├── user_registered → INSERT notification "Welcome!" (type: info)
│   ├── event_created → Log to console (no DB notification)
│   ├── registration_confirmed → INSERT notification "Registration Confirmed" (type: confirmation)
│   └── registration_cancelled → Log to console (no DB notification)
│
├── On success → basic_ack (message removed from queue)
└── On failure → basic_nack with requeue=True (message retried)
```

---

## Cross-cutting Concerns

### Health Checks

Every service exposes `GET /health` returning `{"status": "healthy", "service": "<name>"}`.

Infrastructure health checks:
- **PostgreSQL:** `pg_isready -U postgres` (10s interval)
- **Redis:** `redis-cli ping` (10s interval)
- **RabbitMQ:** `rabbitmq-diagnostics ping` (30s interval, avoids CPU spikes)

### Metrics

All services expose `GET /metrics` via `prometheus_fastapi_instrumentator`. Metrics include:
- `http_requests_total` — counter by method, handler, status
- `http_request_duration_seconds` — histogram (p50, p95, p99)
- `http_request_size_bytes` / `http_response_size_bytes`
- Python runtime metrics (GC, memory, threads)

### Error Handling

- Services use FastAPI's `HTTPException` for 4xx/5xx errors
- RabbitMQ/Redis failures are caught with `try/except` and silently ignored
- DB integrity errors (duplicate key) return 400/409
- Compensating transactions on registration failure

### Security

- **Authentication:** JWT tokens (PyJWT, HS256, 24h expiry) with role claims; Bearer token required on all endpoints except register/login/health
- **Authorization:** RBAC with 3 roles — `super_admin` (full access), `organizer` (manage own events), `attendee` (register, view)
- **Ownership scoping:** Organizers can only modify their own events; users can only access their own registrations and notifications
- **Service-to-service auth:** Internal calls use `X-Service-Key` header (e.g., registration-service → event-service)
- **Password hashing:** bcrypt with 12 rounds
- **Rate limiting:** nginx enforces 5 req/s on auth, 30 req/s on API
- **CORS:** Origin whitelist via `CORS_ORIGINS` environment variable (no more wildcard `*`)
- **Input validation:** Pydantic field validators enforce username format, email format, password length (8-128), valid roles, capacity/price bounds
- **Soft deletes:** Users are deactivated (`is_active=FALSE`), never hard-deleted
- **Secrets:** Production credentials via environment variables, not hardcoded

---

## Container Architecture

### Multi-stage Builds (All Services)

```dockerfile
# Stage 1: Build
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: Runtime
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .
RUN useradd -m appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Benefits:
- Smaller image size (no build tools in runtime)
- Non-root user for security
- Cached dependency layer for faster rebuilds

### Docker Networking

All containers share the `event-network` bridge network. Services reference each other by Docker Compose service name (e.g., `user-service`, `event-service`).

### Volume Strategy

| Volume | Purpose | Persistence |
|--------|---------|-------------|
| `postgres_data` | Database files | Survives restarts |
| `redis_data` | Redis append-only file | Survives restarts |
| `rabbitmq_data` | RabbitMQ state | Survives restarts |
| `prometheus_data` | Metrics storage (15s interval) | Survives restarts |
| `grafana_data` | Dashboard config | Survives restarts |
| `loki_data` | Log storage | Survives restarts |

Production uses separate volumes: `postgres_prod_data`, `redis_prod_data`, `rabbitmq_prod_data`.

---

## Technology Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **API Framework** | FastAPI | Async REST endpoints with auto-docs |
| **Database** | PostgreSQL 16 | Primary data store with connection pooling |
| **Cache** | Redis 7 | Pub-sub, token storage, caching |
| **Message Broker** | RabbitMQ 3 | Topic exchange for async events |
| **API Gateway** | Nginx | Reverse proxy, rate limiting, static files |
| **Metrics** | Prometheus | Time-series metrics collection |
| **Visualization** | Grafana | Dashboards, alerting |
| **Logging** | Loki + Promtail | Centralized log aggregation |
| **Containerization** | Docker | Multi-stage builds |
| **Orchestration** | Docker Compose / Kubernetes | Multi-environment deployment |
| **Authentication** | PyJWT | JWT token generation, validation, RBAC |
| **CI/CD** | GitHub Actions | Automated build + test |
| **Language** | Python 3.11 | Runtime for all services |
