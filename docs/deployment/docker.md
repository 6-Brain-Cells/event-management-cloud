# Docker & Docker Compose Deployment

## Overview

The project uses Docker Compose with overlay files for different environments. Each service runs in its own container with multi-stage Docker builds. The `manage.sh` script provides a convenient CLI for managing all environments.

```mermaid
flowchart TB
    subgraph Base["📋 docker-compose.yml (Base)"]
        B1["postgres:16-alpine"]
        B2["redis:7-alpine"]
        B3["rabbitmq:3-management-alpine"]
        B4["user-service (build)"]
        B5["event-service (build)"]
        B6["registration-service (build)"]
        B7["notification-service (build)"]
        B8["nginx (build)"]
    end

    subgraph Overlays["🔗 Overlay Files"]
        O1["docker-compose.dev.yml\n(hot-reload, exposed ports)"]
        O2["docker-compose.test.yml\n(isolated DB, test-runner)"]
        O3["docker-compose.prod.yml\n(replicas, resource limits)"]
        O4["docker-compose.monitoring.yml\n(Prometheus, Grafana, Loki)"]
    end

    subgraph Commands["⚡ Commands"]
        C1["./manage.sh up dev"]
        C2["./manage.sh up test"]
        C3["./manage.sh up prod"]
        C4["./manage.sh test"]
    end

    Base --> Overlays
    Overlays --> Commands

    style Base fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Overlays fill:#16213e,stroke:#e94560,color:#e94560
    style Commands fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

---

## Compose File Strategy

```mermaid
flowchart LR
    BASE["docker-compose.yml\n(Base shared definitions)"]
    DEV["docker-compose.dev.yml\n(Development overrides)"]
    TEST["docker-compose.test.yml\n(Testing overrides)"]
    PROD["docker-compose.prod.yml\n(Production overrides)"]
    MON["docker-compose.monitoring.yml\n(Monitoring stack)"]

    BASE --> DEV & TEST & PROD & MON

    style BASE fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style DEV fill:#16213e,stroke:#e94560,color:#e94560
    style TEST fill:#16213e,stroke:#e94560,color:#e94560
    style PROD fill:#0f3460,stroke:#00d9ff,color:#00d9ff
    style MON fill:#0f3460,stroke:#e94560,color:#e94560
```

Overlay files are combined using multiple `-f` flags:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up
```

Later files override earlier ones for the same service.

### Project Names

Each environment uses a unique Docker Compose project name (`event-dev`, `event-test`, `event-prod`) so multiple environments can run simultaneously without container name conflicts:

```bash
docker compose -p event-dev -f docker-compose.yml -f docker-compose.dev.yml up
```

---

## Management Script (`manage.sh`)

```mermaid
flowchart TB
    subgraph Commands["📋 Commands"]
        C1["up dev|test|prod"]
        C2["down dev|test|prod"]
        C3["down-all"]
        C4["logs dev|test|prod"]
        C5["build dev|test|prod"]
        C6["test"]
        C7["k8s-up / k8s-down"]
        C8["status"]
        C9["clean"]
    end

    subgraph Flags["🏴 Flags"]
        F1["--monitor\n(+ Prometheus, Grafana, Loki)"]
    end

    Commands --> F1

    style Commands fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Flags fill:#16213e,stroke:#e94560,color:#e94560
```

### Commands

| Command | Description |
|---------|-------------|
| `./manage.sh up dev` | Start dev (http://localhost:8080) |
| `./manage.sh up dev --monitor` | + Prometheus, Grafana, Loki, Promtail |
| `./manage.sh up test` | Start test (http://localhost:8081) |
| `./manage.sh up prod` | Start prod (http://localhost:8082) |
| `./manage.sh down dev` | Stop dev |
| `./manage.sh down-all` | Stop all environments |
| `./manage.sh logs dev` | Tail logs |
| `./manage.sh build dev` | Rebuild images |
| `./manage.sh test` | Run integration tests |
| `./manage.sh k8s-up` | Deploy to Minikube |
| `./manage.sh k8s-down` | Remove from Minikube |
| `./manage.sh status` | Show running containers |
| `./manage.sh clean` | Remove all volumes and containers |

---

## Base (`docker-compose.yml`)

```mermaid
flowchart TB
    subgraph Services["📦 Services"]
        S1["🐘 postgres\npostgres:16-alpine"]
        S2["📡 redis\nredis:7-alpine"]
        S3["🐰 rabbitmq\nrabbitmq:3-management-alpine"]
        S4["👤 user-service\n(build: ./services/user-service)"]
        S5["📅 event-service\n(build: ./services/event-service)"]
        S6["🎫 registration-service\n(build: ./services/registration-service)"]
        S7["🔔 notification-service\n(build: ./services/notification-service)"]
        S8["🚪 nginx\n(build: ./nginx)"]
    end

    subgraph Network["🌉 Network: event-network (bridge)"]
        N1["All containers share this network"]
    end

    subgraph Volumes["💾 Volumes"]
        V1["postgres_data"]
        V2["redis_data"]
        V3["rabbitmq_data"]
    end

    Services --> N1
    S1 --> V1
    S2 --> V2
    S3 --> V3

    style Services fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Network fill:#16213e,stroke:#e94560,color:#e94560
    style Volumes fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

**YAML Anchors:** `x-common-env` and `x-service-defaults` reduce repetition across services.

**Health checks:** postgres, redis, and rabbitmq have health checks; services use `depends_on` with `condition: service_healthy`.

**Network:** All services share `event-network` (bridge driver).

---

## Development (`docker-compose.dev.yml`)

```mermaid
flowchart TB
    subgraph Dev["🛠️ Development Environment"]
        P1["Ports: 8080→nginx, 8001-8004→services\n5432→postgres, 6379→redis\n5672+15672→rabbitmq"]
        V1["Volume mounts:\n./services/<name>:/app (hot-reload)"]
        C1["uvicorn main:app --reload\n(auto-restart on code changes)"]
        E1["ENV=development\nLOG_LEVEL=debug"]
    end

    subgraph Result["📦 Result"]
        R1["Code changes reflected immediately\nNo rebuild required"]
    end

    Dev --> Result

    style Dev fill:#16213e,stroke:#e94560,color:#e94560
    style Result fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

```bash
docker compose -p event-dev -f docker-compose.yml -f docker-compose.dev.yml up --build
```

---

## Testing (`docker-compose.test.yml`)

```mermaid
flowchart TB
    subgraph Test["🧪 Testing Environment"]
        DB["POSTGRES_DB: testdb\n(Isolated from dev)"]
        VOL["postgres_test_data\n(Separate volume)"]
        PORT["8081→nginx\n(Different from dev)"]
        RUNNER["test-runner container\n(python:3.11-slim)\nRuns pytest → exits"]
    end

    subgraph Flow["⚡ Flow"]
        F1["Services start with testdb"]
        F2["test-runner runs pytest"]
        F3["Exit code = test result"]
    end

    Test --> Flow

    style Test fill:#16213e,stroke:#e94560,color:#e94560
    style Flow fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

```bash
docker compose -p event-test -f docker-compose.yml -f docker-compose.test.yml up --build
```

---

## Production (`docker-compose.prod.yml`)

```mermaid
flowchart TB
    subgraph Prod["🚀 Production Environment"]
        REP["user-service: 2 replicas\nevent-service: 2 replicas"]
        RES["0.5 CPU, 256M RAM per service\n(notification: 0.25 CPU, 128M)"]
        CREDS["DB: eventdb_prod + ${DB_PASSWORD}\nRedis: ${REDIS_PASSWORD}\nRabbitMQ: env vars"]
        PORT["8082→nginx only\n(No exposed infra ports)"]
        RESTART["restart: always"]
        LOG["LOG_LEVEL: warning"]
        VOLS["postgres_prod_data\nredis_prod_data\nrabbitmq_prod_data"]
    end

    style Prod fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

```bash
docker compose -p event-prod -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

**Credentials:** Use `.env` file or export environment variables:
```bash
export DB_PASSWORD=your_secure_password
export REDIS_PASSWORD=your_redis_password
export RABBITMQ_PASSWORD=your_rabbitmq_password
```

---

## Monitoring (`docker-compose.monitoring.yml`)

```mermaid
flowchart TB
    subgraph Mon["📊 Monitoring Stack"]
        M1["prometheus\n:v2.48.0 :9090"]
        M2["grafana\n:10.2.0 :3000"]
        M3["loki\n:2.9.3 :3100"]
        M4["promtail\n:2.9.3 :9080"]
        M5["node-exporter\n:v1.7.0 :9100"]
        M6["postgres-exporter\n:v0.15.0 :9187"]
        M7["redis-exporter\n:v1.55.0 :9121"]
    end

    subgraph Data["📋 Auto-Provisioned"]
        D1["Prometheus datasource"]
        D2["Loki datasource"]
        D3["Event Management dashboard\n(15 panels)"]
    end

    Mon --> Data

    style Mon fill:#16213e,stroke:#e94560,color:#e94560
    style Data fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

```bash
docker compose -p event-dev -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.monitoring.yml up
```

---

## Dockerfiles

```mermaid
flowchart TB
    subgraph Build["📦 Build Stage"]
        B1["FROM python:3.11-slim AS builder"]
        B2["COPY requirements.txt ."]
        B3["RUN pip install --no-cache-dir -r requirements.txt"]
    end

    subgraph Runtime["⚙️ Runtime Stage"]
        R1["FROM python:3.11-slim"]
        R2["COPY --from=builder /usr/local/lib/python3.11/site-packages"]
        R3["COPY . ."]
        R4["RUN useradd -m appuser"]
        R5["USER appuser (non-root)"]
        R6["EXPOSE 8000"]
        R7["CMD [\"uvicorn\", \"main:app\", ...]"]
    end

    Build --> Runtime

    style Build fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Runtime fill:#16213e,stroke:#e94560,color:#e94560
```

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
- Smaller runtime image (~80-100MB vs ~900MB for python:3.11)
- Non-root user for security
- Dependency layer cached for faster rebuilds

---

## Common Commands

```mermaid
flowchart TB
    subgraph Quick["⚡ Quick Commands (manage.sh)"]
        Q1["./manage.sh up dev"]
        Q2["./manage.sh up dev --monitor"]
        Q3["./manage.sh down dev"]
        Q4["./manage.sh down-all"]
        Q5["./manage.sh logs dev"]
        Q6["./manage.sh build dev"]
        Q7["./manage.sh test"]
        Q8["./manage.sh clean"]
        Q9["./manage.sh status"]
    end

    subgraph Manual["🔧 Manual Docker Commands"]
        M1["docker compose -p event-dev -f docker-compose.yml \\\n  -f docker-compose.dev.yml up --build"]
        M2["docker compose -p event-dev logs -f user-service"]
        M3["docker compose -p event-dev ps"]
        M4["docker compose -p event-dev down -v"]
    end

    Quick --> Manual

    style Quick fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Manual fill:#16213e,stroke:#e94560,color:#e94560
```

```bash
# Using manage.sh (recommended)
./manage.sh up dev
./manage.sh up dev --monitor
./manage.sh down dev
./manage.sh down-all
./manage.sh logs dev
./manage.sh build dev
./manage.sh test
./manage.sh clean
./manage.sh status

# Manual docker compose commands
docker compose -p event-dev -f docker-compose.yml -f docker-compose.dev.yml up --build
docker compose -p event-dev -f docker-compose.yml -f docker-compose.dev.yml up -d
docker compose -p event-dev logs -f user-service
docker compose -p event-dev -f docker-compose.yml -f docker-compose.dev.yml down -v
docker compose -p event-dev ps
```