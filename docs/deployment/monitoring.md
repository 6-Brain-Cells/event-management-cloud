# Monitoring Stack

## Overview

The monitoring stack provides full observability: metrics collection (Prometheus), visualization (Grafana), log aggregation (Loki + Promtail), and infrastructure exporters.

```mermaid
flowchart TB
    subgraph Services["⚙️ Application Services"]
        S1["👤 user-service :8000/metrics"]
        S2["📅 event-service :8000/metrics"]
        S3["🎫 registration-service :8000/metrics"]
        S4["🔔 notification-service :8000/metrics"]
    end

    subgraph Exporters["📊 Prometheus Exporters"]
        E1["postgres-exporter :9187"]
        E2["redis-exporter :9121"]
        E3["node-exporter :9100"]
    end

    subgraph Monitoring["📡 Monitoring Stack"]
        PROM["Prometheus :9090\n(8 scrape targets, 15s interval)"]
        GRAF["Grafana :3000\n(15 panels, alerting)"]
        LOKI["Loki :3100\n(log storage)"]
        PROMT["Promtail :9080\n(log shipper, Docker discovery)"]
    end

    subgraph Users["👤 Users"]
        U1["Dev/Ops查看Dashboard"]
        U2["Alerts通知"]
    end

    Services --> PROM
    Exporters --> PROM
    PROM --> GRAF
    PROMT --> LOKI
    GRAF --> U1 & U2

    style Services fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Exporters fill:#16213e,stroke:#e94560,color:#e94560
    style Monitoring fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

---

## Components

### Prometheus (`prom/prometheus:v2.48.0`)

```mermaid
flowchart TB
    subgraph Scrape["📡 Scrape Targets (8 total)"]
        T1["user-service :8000/metrics"]
        T2["event-service :8000/metrics"]
        T3["registration-service :8000/metrics"]
        T4["notification-service :8000/metrics"]
        T5["postgres-exporter :9187"]
        T6["redis-exporter :9121"]
        T7["node-exporter :9100"]
        T8["prometheus :9090/metrics"]
    end

    subgraph Metrics["📊 Collected Metrics"]
        M1["http_requests_total (counter)"]
        M2["http_request_duration_seconds (histogram)"]
        M3["pg_stat_activity_count"]
        M4["redis_memory_used_bytes"]
        M5["node_cpu_seconds_total"]
    end

    subgraph Alerts["🚨 Alert Rules"]
        A1["ServiceDown (up==0)"]
        A2["HighErrorRate (5xx>10%)"]
        A3["HighResponseTime (p95>2s)"]
        A4["PostgresConnectionsHigh"]
        A5["RedisMemoryHigh"]
        A6["RabbitMQQueueDepthHigh"]
    end

    Scrape --> Metrics --> Alerts

    style Scrape fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Metrics fill:#16213e,stroke:#e94560,color:#e94560
    style Alerts fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

Collects metrics from all services and exporters every 15 seconds.

| Job | Target | Metrics |
|-----|--------|---------|
| user-service | `http://user-service:8000/metrics` | HTTP, Python runtime |
| event-service | `http://event-service:8000/metrics` | HTTP, Python runtime |
| registration-service | `http://registration-service:8000/metrics` | HTTP, Python runtime |
| notification-service | `http://notification-service:8000/metrics` | HTTP, Python runtime |
| postgres | `http://postgres-exporter:9187/metrics` | DB connections, queries, rows |
| redis | `http://redis-exporter:9121/metrics` | Memory, keys, hit rate |
| node | `http://node-exporter:9100/metrics` | CPU, memory, disk, network |
| prometheus | `http://localhost:9090/metrics` | Self-monitoring |

**Configuration file:** `monitoring/prometheus.yml`

---

### Grafana (`grafana/grafana:10.2.0`)

```mermaid
flowchart TB
    subgraph Panels["📊 Dashboard Panels (15 total)"]
        P1["Service Status (×4)"]
        P2["Infrastructure Status\n(PostgreSQL, Redis, RabbitMQ)"]
        P3["Request Rate (req/s per service)"]
        P4["Response Time (p50, p95, p99)"]
        P5["Error Rate (5xx)"]
        P6["CPU / Memory (per container)"]
        P7["Database connections"]
        P8["Redis hit rate"]
    end

    subgraph AutoProvision["⚡ Auto-Provisioned"]
        AP1["Prometheus datasource\n(http://prometheus:9090)"]
        AP2["Loki datasource\n(http://loki:3100)"]
        AP3["Event Management Overview\n(15 panels JSON)"]
    end

    Panels --> AP1 & AP2 & AP3

    style Panels fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style AutoProvision fill:#16213e,stroke:#e94560,color:#e94560
```

**Default credentials:** admin / admin

**Auto-provisioned resources:**
- **Datasources:** Prometheus + Loki (from `monitoring/grafana-datasources.yml`)
- **Dashboard:** Event Management Overview (15 panels from `monitoring/grafana-dashboards/`)

---

### Loki (`grafana/loki:2.9.3`)

```mermaid
flowchart TB
    subgraph Sources["📥 Log Sources"]
        S1["user-service (JSON logs)"]
        S2["event-service (JSON logs)"]
        S3["registration-service (JSON logs)"]
        S4["notification-service (JSON logs)"]
        S5["nginx (access logs)"]
    end

    subgraph Query["🔍 Query Interface"]
        Q1["Grafana Explore"]
        Q2["LogQL: {service=\"user-service\"}"]
        Q3["LogQL: {service=\"reg*\"} |= \"error\""]
    end

    Sources --> PROMT["Promtail\n(Docker socket discovery)"] --> Loki --> Query

    style Sources fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Query fill:#16213e,stroke:#e94560,color:#e94560
```

Log aggregation engine. Stores logs and provides query interface.

**Configuration:** `monitoring/loki-config.yml`

**Query in Grafana Explore:**
```logql
{service="user-service"}
{service="registration-service"} |= "error"
{service="notification-service"} | json
```

---

### Promtail (`grafana/promtail:2.9.3`)

```mermaid
flowchart TB
    subgraph Discover["🔍 Discovery"]
        D1["Docker socket\n/var/run/docker.sock"]
        D2["Container labels\n(service, namespace)"]
    end

    subgraph Ship["📤 Ship to Loki"]
        S1["Read container logs\n/var/lib/docker/containers/*/*.log"]
        S2["Parse JSON log entries\n(correlation_id, service, level)"]
        S3["Ship to Loki :3100"]
    end

    Discover --> Ship

    style Discover fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Ship fill:#16213e,stroke:#e94560,color:#e94560
```

Log shipper. Discovers Docker containers, reads their logs, and ships to Loki.

**Configuration:** `monitoring/promtail-config.yml`

**Windows note:** On Windows with Docker Desktop, the `/var/lib/docker/containers` path may not be accessible. Promtail will run but may not collect container logs. Loki itself is fully functional for manual log pushes.

---

### Exporters

| Exporter | Image | Port | Scrape Target |
|----------|-------|------|---------------|
| postgres-exporter | `prometheuscommunity/postgres-exporter:v0.15.0` | 9187 | PostgreSQL metrics |
| redis-exporter | `oliver006/redis_exporter:v1.55.0` | 9121 | Redis metrics |
| node-exporter | `prom/node-exporter:v1.7.0` | 9100 | Host system metrics |

---

## Setup

```mermaid
flowchart TB
    subgraph Docker["🐳 Docker Compose"]
        DC1["docker compose -f docker-compose.yml \\\n  -f docker-compose.dev.yml \\\n  -f docker-compose.monitoring.yml \\\n  up --build"]
    end

    subgraph K8s["☸️ Kubernetes"]
        K1["kubectl apply -f k8s/monitoring/"]
    end

    subgraph Access["🔗 Access URLs"]
        A1["Prometheus: http://localhost:9090"]
        A2["Grafana: http://localhost:3000\n(admin/admin)"]
        A3["Loki: http://localhost:3100"]
    end

    Docker & K8s --> Access

    style Docker fill:#16213e,stroke:#e94560,color:#e94560
    style K8s fill:#16213e,stroke:#e94560,color:#e94560
    style Access fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

---

## Useful Queries

### Prometheus (PromQL)

```mermaid
flowchart TB
    subgraph Queries["📊 PromQL Queries"]
        Q1["Request rate:\nrate(http_requests_total[5m])"]
        Q2["95th percentile:\nhistogram_quantile(0.95,\nrate(http_request_duration_seconds_bucket[5m]))"]
        Q3["Error rate:\nrate(http_requests_total{status=~\"5..\"}[5m]) /\nrate(http_requests_total[5m])"]
        Q4["Memory:\nprocess_resident_memory_bytes"]
        Q5["DB connections:\npg_stat_activity_count"]
    end

    style Queries fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
```

```
# Request rate per service
rate(http_requests_total[5m])

# 95th percentile response time
histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[5m]))

# Error rate
rate(http_requests_total{status=~"5.."}[5m]) / rate(http_requests_total[5m])

# Python process memory
process_resident_memory_bytes

# Database connections
pg_stat_activity_count
```

### Loki (LogQL)

```
# All logs from user-service
{service="user-service"}

# Error logs
{service="user-service"} |= "ERROR"

# Registration success logs
{service="registration-service"} |= "Registration successful"
```