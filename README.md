# Event Management System — Cloud & DevOps Project

A microservices-based event management platform demonstrating containerization, orchestration, async messaging, monitoring, and multi-environment deployment.

---

## Table of Contents

- [Architecture Overview](#architecture-overview)
- [Microservices](#microservices)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Folder Descriptions](#folder-descriptions)
- [Getting Started](#getting-started)
- [Environments](#environments)
- [API Reference](#api-reference)
- [Monitoring & Observability](#monitoring--observability)
- [Kubernetes Deployment](#kubernetes-deployment)
- [CI/CD](#cicd)
- [Testing](#testing)

---

## Architecture Overview

```
                          ┌─────────────────────────────────────────┐
                          │           Nginx (API Gateway)            │
                          │   Rate Limiting / Reverse Proxy / TLS   │
                          │              Port 80/8080                │
                          └──────┬──────┬──────┬──────┬─────────────┘
                                 │      │      │      │
                  ┌──────────────┘      │      │      └──────────────┐
                  ▼                     ▼      ▼                     ▼
          ┌───────────────┐   ┌───────────────┐  ┌────────────────┐  ┌──────────────────┐
          │  User Service  │   │ Event Service  │  │ Registration   │  │ Notification     │
          │   :8001        │   │   :8002        │  │ Service :8003  │  │ Service :8004    │
          │   FastAPI       │   │   FastAPI      │  │   FastAPI      │  │   FastAPI        │
          └───────┬────────┘   └───────┬────────┘  └───────┬────────┘  └───────┬──────────┘
                  │                    │                    │                   │
                  │        ┌───────────┴────────────────────┘                   │
                  │        │  Sync HTTP (httpx) for capacity checks             │
                  │        │                                                    │
                  ▼        ▼                                                    ▼
          ┌──────────────────────────────────────────────────────────────────────────┐
          │                         Async Messaging (RabbitMQ)                       │
          │  Exchange: "events" (topic)                                              │
          │  Routing keys: user.registered, event.created,                           │
          │                 registration.confirmed, registration.cancelled            │
          │  Consumer: notification-service ← notification_queue                      │
          └──────────────────────────────────────────────────────────────────────────┘
                                           │
                  ┌────────────────────────┼────────────────────────────┐
                  ▼                        ▼                            ▼
          ┌──────────────┐        ┌──────────────┐             ┌──────────────┐
          │  PostgreSQL   │        │    Redis      │             │   RabbitMQ   │
           │  (Primary DB) │        │  (Cache/      │             │  (Message    │
           │  Port 5432    │        │   Pub-Sub)    │             │   Broker)    │
           │               │        │  Port 6379    │             │  5672/15672  │
          └──────────────┘        └──────────────┘             └──────────────┘
```

### Communication Patterns

| Pattern | Technology | Example |
|---------|-----------|---------|
| **Sync request/response** | HTTP (httpx) | Registration service calls event-service to check/increment capacity |
| **Async fire-and-forget** | RabbitMQ (topic exchange) | User service publishes `user.registered` → notification-service consumes |
| **Cache/Pub-Sub** | Redis | Services publish to Redis channels as secondary notification path |
| **API Gateway** | Nginx | All external traffic routes through nginx with rate limiting |
| **Service-to-service** | X-Service-Key header | Registration service authenticates to event-service for capacity operations |

### Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Language | Python 3.11 + FastAPI | Async support, auto-docs, lightweight |
| Password hashing | bcrypt (12 rounds) | Industry standard, adaptive cost |
| DB connections | ThreadedConnectionPool (2-10) | Reuse connections, avoid per-request overhead |
| Payment processing | Mock gateway with 5% random decline | Simulates real payment failures for testing |
| Capacity management | Increment-then-pay with compensating decrement | Prevents race conditions in concurrent registrations |
| Notification delivery | RabbitMQ consumer only (no Redis subscriber) | Prevents duplicate notifications from dual sources |
| Authentication | JWT (PyJWT, HS256, 24h expiry) | Stateless auth with role claims, Redis session store |
| Authorization | RBAC with 3 roles (super_admin, organizer, attendee) | Role-based access control enforced per endpoint |
| Input validation | Pydantic field validators | Username, email, password, role validation at API layer |
| Optimistic concurrency | `version` column on events table | PUT/DELETE require version; 409 on mismatch prevents lost updates |
| Database migrations | Alembic per service | Version-controlled schema changes; fallback to CREATE TABLE IF NOT EXISTS on startup |
| Redis caching | Event listing cache with 30s TTL | Reduces DB load for high-traffic list endpoints |
| CORS | Origin whitelist via CORS_ORIGINS env var | Restrict cross-origin access to known frontend hosts |
| Service-to-service auth | X-Service-Key header | Internal services authenticate to each other via shared key |

---

## Microservices

### User Service (`services/user-service/`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/users/register` | POST | Public | Register new user with role (bcrypt hashing) |
| `/users/login` | POST | Public | Authenticate, return JWT token |
| `/users` | GET | Any user | List all active users |
| `/users/me` | GET | Any user | Get current user profile from JWT |
| `/users/{id}` | GET | Any user | Get user by ID |
| `/users/{id}/role` | PUT | super_admin | Update user role |
| `/users/{id}` | DELETE | Self or super_admin | Soft-delete (is_active=FALSE) |
| `/health` | GET | Public | Service health check |

**Publishes:** `user.registered` to RabbitMQ

### Event Service (`services/event-service/`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/events` | POST | organizer, super_admin | Create event |
| `/events` | GET | Any user or service | List events (filter by type, status; paginated with page/page_size) |
| `/events/{id}` | GET | Any user or service | Get event by ID |
| `/events/{id}` | PUT | organizer (own), super_admin | Update event fields (requires `version` in body; returns 409 on conflict) |
| `/events/{id}` | DELETE | organizer (own), super_admin | Cancel event (requires `?version=N` query param; returns 409 on conflict) |
| `/events/{id}/increment-registration` | PATCH | Service key or super_admin | Atomically increment registered_count |
| `/events/{id}/decrement-registration` | PATCH | Service key or super_admin | Atomically decrement registered_count |
| `/health` | GET | Public | Service health check |

**Publishes:** `event.created` to RabbitMQ

### Registration Service (`services/registration-service/`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/registrations` | POST | attendee, organizer, super_admin | Register for event (user_id from JWT) |
| `/registrations` | GET | Any user (own only; super_admin sees all) | List registrations (paginated with page/page_size) |
| `/registrations/{id}` | GET | Own user or super_admin | Get registration by ID |
| `/registrations/user/{user_id}` | GET | Own user or super_admin | List registrations by user |
| `/registrations/event/{event_id}` | GET | Any user | List confirmed registrations by event |
| `/registrations/{id}/payment` | PATCH | super_admin | Update payment status |
| `/registrations/{id}/process-payment` | POST | Own user or super_admin | Retry payment processing |
| `/registrations/{id}` | DELETE | Own user or super_admin | Cancel registration |
| `/health` | GET | Public | Service health check |

**Publishes:** `registration.confirmed`, `registration.cancelled` to RabbitMQ

**Flow:** Fetch event → Increment capacity → Process payment → Insert registration → On failure: compensating decrement

### Notification Service (`services/notification-service/`)

| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/notifications` | POST | super_admin | Create notification |
| `/notifications/user/{user_id}` | GET | Own user or super_admin | List notifications by user |
| `/notifications/{id}/read` | PATCH | Own user or super_admin | Mark notification as read |
| `/notifications/broadcast` | POST | super_admin | Send notification to multiple users |
| `/health` | GET | Public | Service health check |

**Consumes:** All routing keys from `events` exchange via `notification_queue` (RabbitMQ consumer thread)

---

## Technology Stack

| Category | Technology | Version | Purpose |
|----------|-----------|---------|---------|
| **Runtime** | Python | 3.11-slim | Application runtime |
| **Framework** | FastAPI | Latest | REST API framework |
| **Database** | PostgreSQL | 16-alpine | Primary data store |
| **Cache** | Redis | 7-alpine | Caching, pub-sub |
| **Message Broker** | RabbitMQ | 3-management-alpine | Async messaging |
| **API Gateway** | Nginx | Latest | Reverse proxy, rate limiting |
| **Metrics** | Prometheus | 2.48.0 | Metrics collection |
| **Visualization** | Grafana | 10.2.0 | Dashboards |
| **Logging** | Loki + Promtail | 2.9.3 | Centralized log aggregation |
| **DB Driver** | psycopg2 | Latest | PostgreSQL connection pooling |
| **HTTP Client** | httpx | Latest | Inter-service communication |
| **Password** | bcrypt | Latest | Secure password hashing |
| **Messaging** | pika | Latest | RabbitMQ client |
| **Auth** | PyJWT | 2.8.0+ | JWT token generation and validation (HS256) |
| **Migrations** | Alembic | 1.13.0+ | Database schema migrations per service |
| **Migrations ORM** | SQLAlchemy | 2.0.0+ | Required by Alembic for migration engine |
| **Metrics** | prometheus-fastapi-instrumentator | Latest | Auto-instrument HTTP metrics |
| **Containerization** | Docker | — | Multi-stage builds |
| **Orchestration** | Kubernetes (Minikube) | — | Production deployment |
| **CI** | GitHub Actions | — | Automated testing |

---

## Project Structure

```
event-management-cloud/
├── .github/
│   └── workflows/
│       └── ci.yml                          # GitHub Actions CI pipeline
├── docker-compose.yml                      # Base definitions (shared services)
├── docker-compose.dev.yml                  # Development overrides (hot-reload, exposed ports)
├── docker-compose.test.yml                 # Testing overrides (isolated testdb)
├── docker-compose.prod.yml                 # Production overrides (replicas, resource limits)
├── docker-compose.monitoring.yml           # Prometheus, Grafana, Loki, Promtail, exporters
├── manage.sh                               # Management helper script
├── README.md                               # This file
│
├── services/                               # Microservices (each = separate Docker container)
│   ├── user-service/
│   │   ├── main.py                         # FastAPI app, routes, models, DB schema
│   │   ├── Dockerfile                      # Multi-stage build
│   │   ├── requirements.txt                # Python dependencies
│   │   ├── alembic.ini                     # Alembic config (version_table: alembic_version_user)
│   │   ├── alembic/                        # Database migrations
│   │   │   ├── env.py                      # Migration environment
│   │   │   ├── script.py.mako             # Migration script template
│   │   │   └── versions/
│   │   │       └── 001_create_users_table.py
│   │   └── .dockerignore
│   ├── event-service/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── alembic.ini                     # Alembic config (version_table: alembic_version_event)
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   ├── script.py.mako
│   │   │   └── versions/
│   │   │       └── 001_create_events_table.py  # Includes version column + migration
│   │   └── .dockerignore
│   ├── registration-service/
│   │   ├── main.py
│   │   ├── Dockerfile
│   │   ├── requirements.txt
│   │   ├── alembic.ini                     # Alembic config (version_table: alembic_version_registration)
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   ├── script.py.mako
│   │   │   └── versions/
│   │   │       └── 001_create_registrations_table.py
│   │   └── .dockerignore
│   └── notification-service/
│       ├── main.py
│       ├── Dockerfile
│       ├── requirements.txt
│       ├── alembic.ini                     # Alembic config (version_table: alembic_version_notification)
│       ├── alembic/
│       │   ├── env.py
│       │   ├── script.py.mako
│       │   └── versions/
│       │       └── 001_create_notifications_table.py
│       └── .dockerignore
│
├── nginx/                                  # API Gateway + Frontend
│   ├── nginx.conf                          # Reverse proxy config, rate limiting
│   ├── Dockerfile                          # Multi-stage build
│   ├── .dockerignore
│   ├── index.html                          # Frontend pages
│   ├── users.html
│   ├── events.html
│   ├── registrations.html
│   ├── notifications.html
│   └── assets/
│       ├── style.css                       # Shared styles
│       └── api.js                          # API client helpers
│
├── monitoring/                             # Observability stack configuration
│   ├── prometheus.yml                      # Scrape targets for all services + exporters
│   ├── grafana-datasources.yml             # Auto-provisioned Prometheus + Loki datasources
│   ├── grafana-dashboard-providers.yml     # Dashboard auto-provisioning config
│   ├── grafana-dashboards/
│   │   └── event-management-overview.json  # 15-panel Grafana dashboard
│   ├── loki-config.yml                     # Log aggregation config
│   └── promtail-config.yml                 # Log shipping from Docker containers
│
├── k8s/                                    # Kubernetes manifests
│   ├── configmaps/
│   │   └── config.yaml                     # ConfigMap + Secret (DB, Redis, RabbitMQ credentials)
│   ├── deployments/
│   │   └── deployments.yaml                # 11 Deployments, 1 DaemonSet, 2 PVCs
│   ├── services/
│   │   └── services.yaml                   # 12 Services (ClusterIP + NodePort)
│   └── monitoring/
│       ├── prometheus-deployment.yaml      # Prometheus with RBAC (ServiceAccount, ClusterRole)
│       ├── grafana-deployment.yaml         # Grafana with auto-provisioned datasources
│       ├── loki-deployment.yaml            # Log aggregation
│       └── promtail-daemonset.yaml         # Log shipper (runs on every node)
│
├── tests/
│   └── test_api.py                         # Integration tests (pytest + requests)
│
└── docs/                                   # Project documentation
    ├── architecture/
    │   └── overview.md                     # Architecture deep-dive
    ├── services/
    │   ├── user-service.md                 # User service specification
    │   ├── event-service.md                # Event service specification
    │   ├── registration-service.md         # Registration service specification
    │   └── notification-service.md         # Notification service specification
    ├── infrastructure/
    │   ├── database.md                     # Database schema, indexes, connection pooling
    │   ├── rabbitmq.md                     # Messaging topology, exchanges, queues
    │   ├── redis.md                        # Redis usage, pub-sub channels
    │   └── nginx.md                        # Gateway config, rate limiting, routes
    ├── api/
    │   └── endpoints.md                    # Full API reference with examples
    └── deployment/
        ├── docker.md                       # Docker & Compose deployment guide
        ├── kubernetes.md                   # K8s deployment guide
        └── monitoring.md                   # Monitoring stack setup
```

---

## Folder Descriptions

### `services/`

Contains four independent FastAPI microservices. Each service has its own Dockerfile, requirements.txt, and .dockerignore. Services are independently deployable and scale horizontally.

- **Shared patterns across all services:** DB connection pooling (`ThreadedConnectionPool`), Redis singleton, RabbitMQ publisher, Prometheus instrumentation, CORS middleware (origin whitelist), JWT authentication, RBAC role checking, Pydantic input validation, health endpoint, Alembic database migrations (with fallback to `CREATE TABLE IF NOT EXISTS`)
- **Each service owns its own table** but shares the same PostgreSQL database
- **Each service has its own Alembic migration chain** with separate version tables (`alembic_version_user`, `alembic_version_event`, `alembic_version_registration`, `alembic_version_notification`) to avoid conflicts in the shared database

### `nginx/`

API gateway and static frontend. Routes external requests to internal services, enforces rate limits, and serves HTML pages. Multi-stage Docker build copies static assets into the nginx image.

- **Rate limits:** Auth endpoints (5 req/s), API endpoints (30 req/s)
- **Timeouts:** Connect 5s, read 30s, send 30s
- **Static caching:** JS/CSS/images cached 7 days

### `monitoring/`

Configuration files for the observability stack. Mounted read-only into their respective containers.

- `prometheus.yml` — Scrapes 8 targets (4 services + 4 exporters)
- `grafana-datasources.yml` — Auto-provisions Prometheus and Loki as data sources
- `grafana-dashboard-providers.yml` — Tells Grafana where to find dashboard JSON files
- `event-management-overview.json` — Pre-built dashboard with 15 panels
- `loki-config.yml` + `promtail-config.yml` — Centralized log collection from Docker containers

### `k8s/`

Kubernetes manifests for production deployment. Designed for Minikube with locally built images (`imagePullPolicy: Never`).

- **ConfigMaps + Secrets:** Centralized configuration, credentials via secretKeyRef
- **Deployments:** 11 Deployments (4 services + postgres + redis + rabbitmq + nginx + monitoring stack), 1 DaemonSet (promtail), 2 PVCs (postgres 1Gi, redis 512Mi)
- **Services:** ClusterIP for internal communication, NodePort for external access
- **RBAC:** Prometheus has ServiceAccount + ClusterRole + ClusterRoleBinding for Kubernetes service discovery

### `tests/`

Integration tests using pytest. Runs against the full stack via the test Docker Compose overlay.

### `.github/`

GitHub Actions CI pipeline. Runs on push/PR, executes tests via `manage.sh test`.

---

## Getting Started

### Prerequisites

- Docker Desktop (or Docker Engine + Docker Compose)
- 4 GB RAM minimum (8 GB recommended)
- Git

### Quick Start (Development)

```bash
# Clone the repository
git clone <repo-url>
cd event-management-cloud

# Start all services with hot-reload + monitoring
docker compose -f docker-compose.yml \
               -f docker-compose.dev.yml \
               -f docker-compose.monitoring.yml \
               up --build

# Wait for all health checks to pass (~30 seconds)
```

### Access Points

| Service | URL | Credentials |
|---------|-----|------------|
| Frontend (nginx) | http://localhost:8080 | — |
| User Service | http://localhost:8001 | — |
| Event Service | http://localhost:8002 | — |
| Registration Service | http://localhost:8003 | — |
| Notification Service | http://localhost:8004 | — |
| Prometheus | http://localhost:9090 | — |
| Grafana | http://localhost:3000 | admin / admin |
| RabbitMQ Management | http://localhost:45672 | guest / guest |
| PostgreSQL | localhost:15432 | postgres / postgres |
| Redis | localhost:16379 | — |

### Quick API Test

```bash
# Register an organizer
curl -X POST http://localhost:8080/api/users/register \
  -H "Content-Type: application/json" \
  -d '{"username":"alice","email":"alice@test.com","password":"Password123","full_name":"Alice","role":"organizer"}'

# Login (returns JWT token)
curl -X POST http://localhost:8080/api/users/login \
  -H "Content-Type: application/json" \
  -d '{"email":"alice@test.com","password":"Password123"}'

# Save the token from login response, then:
TOKEN="eyJ..."

# Create an event (requires organizer or super_admin role)
curl -X POST http://localhost:8080/api/events \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"title":"Tech Summit","description":"Annual conference","event_type":"conference","start_date":"2026-07-01 09:00:00","end_date":"2026-07-03 18:00:00","location":"Convention Center","max_capacity":200,"ticket_price":49.99}'

# List events (paginated)
curl "http://localhost:8080/api/events?page=1&page_size=10" -H "Authorization: Bearer $TOKEN"

# Update an event (requires version for optimistic concurrency)
curl -X PUT http://localhost:8080/api/events/1 \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"title":"Tech Summit 2026","version":1}'

# Cancel an event (requires version query param)
curl -X DELETE "http://localhost:8080/api/events/1?version=2" \
  -H "Authorization: Bearer $TOKEN"

# Register for event (user_id derived from JWT token)
curl -X POST http://localhost:8080/api/registrations \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"event_id":1,"payment_method":"card"}'

# View notifications (scoped to own user)
curl http://localhost:8080/api/notifications/user/1 \
  -H "Authorization: Bearer $TOKEN"
```

---

## Environments

| Environment | Command | Port | DB | Special Features |
|-------------|---------|------|----|-----------------|
| **Development** | `-f docker-compose.yml -f docker-compose.dev.yml up` | 8080 | eventdb | Hot-reload, exposed service ports, debug logging |
| **Testing** | `-f docker-compose.yml -f docker-compose.test.yml up` | 8081 | testdb | Isolated DB, test-runner container |
| **Production** | `-f docker-compose.yml -f docker-compose.prod.yml up` | 8082 | eventdb_prod | 2 replicas, resource limits, secure credentials |
| **+ Monitoring** | Append `-f docker-compose.monitoring.yml` to any | — | — | Prometheus, Grafana, Loki, exporters |

### Development

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

- Volume mounts for hot-reload (code changes reflected without rebuild)
- Direct service port access for debugging (8001-8004)
- PostgreSQL and Redis ports exposed for local tools
- Debug-level logging

### Testing

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up --build
```

- Separate `testdb` database
- Test runner container (pytest) auto-runs and exits
- Services use isolated volume (`postgres_test_data`)

### Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

- User/Event services: 2 replicas each
- Resource limits per service (CPU/memory)
- Production database (`eventdb_prod`)
- Credentials via environment variables (`${DB_PASSWORD}`, etc.)
- No exposed infrastructure ports (postgres, redis internal only)

---

## API Reference

All endpoints are accessed through the nginx gateway at `http://localhost:8080/api/`.

### Nginx Route Mapping

| Gateway Route | Upstream Route | Service |
|--------------|---------------|---------|
| `/api/users/register` | `/users/register` | user-service |
| `/api/users/login` | `/users/login` | user-service |
| `/api/users` | `/users` | user-service |
| `/api/events` | `/events` | event-service |
| `/api/registrations` | `/registrations` | registration-service |
| `/api/notifications` | `/notifications` | notification-service |

### Payment Processing

The registration service includes a mock payment gateway supporting:

| Method | Behavior |
|--------|----------|
| `free` | Always succeeds (for events with ticket_price=0) |
| `card` / `credit_card` | 95% success, 5% random decline |
| `paypal` | 95% success, 5% random decline |
| `bank_transfer` | 95% success, 5% random decline |

On payment failure, the system automatically performs a compensating transaction (decrements event capacity) and returns HTTP 402.

---

## Monitoring & Observability

### Prometheus Targets (8 total)

| Target | Scrape URL | Description |
|--------|-----------|-------------|
| user-service | `http://user-service:8000/metrics` | HTTP metrics, Python runtime |
| event-service | `http://event-service:8000/metrics` | HTTP metrics, Python runtime |
| registration-service | `http://registration-service:8000/metrics` | HTTP metrics, Python runtime |
| notification-service | `http://notification-service:8000/metrics` | HTTP metrics, Python runtime |
| postgres-exporter | `http://postgres-exporter:9187/metrics` | Database metrics |
| redis-exporter | `http://redis-exporter:9121/metrics` | Cache metrics |
| node-exporter | `http://node-exporter:9100/metrics` | System metrics |
| prometheus | `http://localhost:9090/metrics` | Self-monitoring |

### Grafana Dashboard (15 panels)

- Service Status (4 panels)
- Infrastructure Status (PostgreSQL, Redis, RabbitMQ)
- Request Rate (req/s per service)
- Response Time (p50, p95, p99)
- Error Rate (5xx responses)
- CPU / Memory per container
- Database connections
- Redis hit rate

### Log Aggregation

Promtail collects container logs from Docker and ships them to Loki. Query in Grafana Explore:

```
{service="user-service"}
{service="registration-service"} |= "error"
```

---

## Kubernetes Deployment

### Prerequisites

- Minikube
- kubectl
- Docker (images built locally)

### Deploy

```bash
# Start Minikube
minikube start

# Build images in Minikube's Docker daemon
eval $(minikube docker-env)
docker compose -f docker-compose.yml build

# Apply manifests
kubectl apply -f k8s/configmaps/
kubectl apply -f k8s/services/
kubectl apply -f k8s/deployments/
kubectl apply -f k8s/monitoring/

# Wait for pods
kubectl get pods -w
```

### K8s Resources Summary

| Type | Count | Details |
|------|-------|---------|
| Deployments | 11 | 4 services + postgres + redis + rabbitmq + nginx + prometheus + grafana + loki |
| DaemonSets | 1 | promtail (log collection on every node) |
| Services | 12 | ClusterIP for internal, NodePort for external |
| ConfigMaps | 1 | Application configuration |
| Secrets | 1 | DB, Redis, RabbitMQ credentials |
| PVCs | 2 | postgres (1Gi), redis (512Mi) |
| ServiceAccounts | 1 | Prometheus |
| ClusterRoles | 1 | Prometheus kube-api access |
| ClusterRoleBindings | 1 | Prometheus RBAC binding |

---

## CI/CD

### GitHub Actions Pipeline

`.github/workflows/ci.yml` runs on every push and pull request:

1. Checks out code
2. Sets up Docker Buildx
3. Builds all service images
4. Runs integration tests via `manage.sh test`

---

## Testing

```bash
# Run integration tests
docker compose -f docker-compose.yml -f docker-compose.test.yml up --build test-runner

# Or use the management script
./manage.sh test
```

### Test Coverage

- User registration, login, retrieval, deletion
- Event CRUD, capacity management
- Registration with payment processing (success/failure)
- Notification delivery verification
- Cross-service communication via RabbitMQ
- JWT authentication: login returns valid token, expired/invalid tokens rejected
- RBAC: attendee cannot create events, organizer can CRUD own events, super_admin has full access
- Input validation: username format, email format, password length, valid roles
- Ownership scoping: users can only access their own data, organizers can only modify their own events
- Service-to-service authentication via X-Service-Key
- Optimistic concurrency: stale version on PUT/DELETE returns 409 with conflict details
- Database migrations: Alembic migrations apply on startup, fallback to CREATE TABLE IF NOT EXISTS

---

## Database Schema

### Tables

| Table | Service | Columns |
|-------|---------|---------|
| `users` | user-service | id, username, email, password_hash, full_name, **role**, created_at, is_active |
| `events` | event-service | id, title, description, event_type, start_date, end_date, location, max_capacity, registered_count, organizer_id, ticket_price, status, **version**, created_at |
| `registrations` | registration-service | id, user_id, event_id, registration_date, status, payment_method, payment_status, payment_reference, payment_gateway, payment_processed_at, ticket_number, notes |
| `notifications` | notification-service | id, user_id, title, message, notification_type, is_read, created_at |

### Indexes

| Table | Index | Purpose |
|-------|-------|---------|
| `users` | `idx_users_email` | Fast email lookup (WHERE is_active=TRUE) |
| `events` | `idx_events_status_type` | Filter by status + event_type |
| `events` | `idx_events_start_date` | Sort by date |
| `events` | `idx_events_organizer` | Lookup events by organizer (ownership scoping) |
| `registrations` | `idx_reg_user` | User's registrations |
| `registrations` | `idx_reg_event_status` | Event attendees |
| `notifications` | `idx_notifications_user_read` | User's notifications with read filter |

### Connection Pooling

Each service uses `psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=10)` to reuse database connections across requests. Pool sizes and timeouts are configurable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_POOL_MIN` | `2` | Minimum connections kept open |
| `DB_POOL_MAX` | `10` | Maximum connections allowed |
| `DB_CONNECT_TIMEOUT` | `5` | Connection timeout in seconds |
| `CACHE_TTL` | `30` | Redis cache TTL in seconds for event listings |

---

## Management Script

```bash
./manage.sh <command> [env] [--monitor]

Commands:
  up dev|test|prod       Start environment
  down dev|test|prod     Stop environment
  down-all               Stop all environments simultaneously
  logs dev|test|prod     Tail logs
  build dev|test|prod    Rebuild images
  test                   Run integration tests
  k8s-up                 Deploy to Minikube
  k8s-down               Remove from Minikube
  status                 Show running containers
  clean                  Remove all volumes and containers

Examples:
  ./manage.sh up dev               # Start dev (http://localhost:8080)
  ./manage.sh up dev --monitor     # + Prometheus, Grafana, Loki, Promtail
  ./manage.sh up prod              # Start prod (http://localhost:8082)
  ./manage.sh down-all             # Stop everything
```

Each environment uses a unique project name (`event-dev`, `event-test`, `event-prod`) so multiple environments can run simultaneously without container conflicts.

---

## License

This project is built for educational purposes as part of a Cloud Computing & DevOps course.
