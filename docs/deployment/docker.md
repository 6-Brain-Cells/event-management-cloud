# Docker & Docker Compose Deployment

## Overview

The project uses Docker Compose with overlay files for different environments. Each service runs in its own container with multi-stage Docker builds.

---

## Compose File Strategy

```
docker-compose.yml              ← Base (shared definitions)
docker-compose.dev.yml          ← Development overrides
docker-compose.test.yml         ← Testing overrides
docker-compose.prod.yml         ← Production overrides
docker-compose.monitoring.yml   ← Monitoring stack (add to any environment)
```

Overlay files are combined using multiple `-f` flags:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Later files override earlier ones for the same service.

---

## Base (`docker-compose.yml`)

Defines all services with sensible defaults:

| Service | Image | Build Context |
|---------|-------|---------------|
| postgres | `postgres:16-alpine` | — |
| redis | `redis:7-alpine` | — |
| rabbitmq | `rabbitmq:3-management-alpine` | — |
| user-service | — | `./services/user-service` |
| event-service | — | `./services/event-service` |
| registration-service | — | `./services/registration-service` |
| notification-service | — | `./services/notification-service` |
| nginx | — | `./nginx` |

**YAML Anchors:** `x-common-env` and `x-service-defaults` reduce repetition across services.

**Health checks:** postgres, redis, and rabbitmq have health checks; services use `depends_on` with `condition: service_healthy`.

**Network:** All services share `event-network` (bridge driver).

**Volumes:** `postgres_data`, `redis_data`, `rabbitmq_data` persist data.

---

## Development (`docker-compose.dev.yml`)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

| Override | Purpose |
|----------|---------|
| Port mappings | 8080→nginx, 8001-8004→services, 5432→postgres, 6379→redis, 5672+15672→rabbitmq |
| Volume mounts | `./services/<name>:/app` for hot-reload |
| Command override | `uvicorn main:app --reload` for auto-restart on code changes |
| Environment | `ENV=development`, `LOG_LEVEL=debug` |

**Hot-reload:** Code changes on the host are immediately reflected in the container. Restart the service with `docker compose restart <service>` to pick up changes.

---

## Testing (`docker-compose.test.yml`)

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up --build
```

| Override | Purpose |
|----------|---------|
| Database | `POSTGRES_DB: testdb` (isolated) |
| Volume | `postgres_test_data` (separate from dev) |
| Port | 8081→nginx (different from dev) |
| Environment | `DB_NAME: testdb`, `ENV: testing` |
| test-runner | `python:3.11-slim` container that runs pytest and exits |

---

## Production (`docker-compose.prod.yml`)

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

| Override | Purpose |
|----------|---------|
| Replicas | user-service: 2, event-service: 2 |
| Resource limits | 0.5 CPU, 256M RAM per service |
| Database | `eventdb_prod` with `${DB_PASSWORD}` |
| Redis | Password via `${REDIS_PASSWORD}` |
| RabbitMQ | Custom user/password via env vars |
| Ports | 8082→nginx only (no exposed infra ports) |
| Restart | `always` |
| Logging | `LOG_LEVEL: warning` |

**Credentials:** Use `.env` file or export environment variables:
```bash
export DB_PASSWORD=your_secure_password
export REDIS_PASSWORD=your_redis_password
export RABBITMQ_PASSWORD=your_rabbitmq_password
```

---

## Monitoring (`docker-compose.monitoring.yml`)

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.monitoring.yml up
```

Adds 7 containers:

| Service | Image | Port |
|---------|-------|------|
| prometheus | `prom/prometheus:v2.48.0` | 9090 |
| grafana | `grafana/grafana:10.2.0` | 3000 |
| loki | `grafana/loki:2.9.3` | 3100 |
| promtail | `grafana/promtail:2.9.3` | 9080 |
| node-exporter | `prom/node-exporter:v1.7.0` | 9100 |
| postgres-exporter | `prometheuscommunity/postgres-exporter:v0.15.0` | 9187 |
| redis-exporter | `oliver006/redis_exporter:v1.55.0` | 9121 |

---

## Dockerfiles

All service Dockerfiles follow the same multi-stage pattern:

```dockerfile
FROM python:3.11-slim AS builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY . .
RUN useradd -m appuser
USER appuser
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

**Benefits:**
- Smaller runtime image (no pip, no build tools)
- Non-root user for security
- Dependency layer cached for faster rebuilds

---

## Common Commands

```bash
# Build and start
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build

# Start in background
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# View logs
docker compose logs -f user-service
docker compose logs -f --tail=50

# Restart a single service
docker compose restart user-service

# Rebuild a single service
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d user-service

# Stop all
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.monitoring.yml down

# Remove volumes (clean slate)
docker compose -f docker-compose.yml -f docker-compose.dev.yml down -v

# Check status
docker compose ps
```
