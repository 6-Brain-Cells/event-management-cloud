# Monitoring Stack

## Overview

The monitoring stack provides full observability: metrics collection (Prometheus), visualization (Grafana), log aggregation (Loki + Promtail), and infrastructure exporters.

---

## Architecture

```
┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│ user-service  │  │ event-service │  │ registration │  │ notification │
│   :8000/metrics│  │   :8000/metrics│  │ :8000/metrics │  │ :8000/metrics│
└──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
       │                 │                 │                 │
       └─────────┬───────┴─────────┬───────┘                 │
                 │                 │                         │
┌────────────────┴────────┐  ┌────┴─────────────┐  ┌───────┴──────────┐
│ postgres-exporter :9187 │  │ redis-exporter    │  │ node-exporter    │
└───────────┬─────────────┘  │     :9121         │  │     :9100        │
            │                └──────┬────────────┘  └──────┬──────────┘
            │                       │                      │
            └───────────┬───────────┴──────────────────────┘
                        │
                        ▼
               ┌────────────────┐
               │  Prometheus    │
               │  :9090         │
               │  (scrape all)  │
               └───────┬────────┘
                       │
         ┌─────────────┤
         │             │
         ▼             ▼
┌────────────────┐  ┌────────────────┐
│    Grafana      │  │     Loki       │
│    :3000        │  │    :3100       │
│  (dashboards)  │  │  (log store)   │
└────────────────┘  └───────┬────────┘
                            ▲
                    ┌───────┴────────┐
                    │   Promtail     │
                    │   :9080        │
                    │ (log shipper)  │
                    └────────────────┘
```

---

## Components

### Prometheus (`prom/prometheus:v2.48.0`)

Collects metrics from all services and exporters every 15 seconds.

**Scrape targets (8 total):**

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

Visualizes metrics and logs. Auto-provisioned on first start.

**Default credentials:** admin / admin

**Auto-provisioned resources:**
- **Datasources:** Prometheus + Loki (from `monitoring/grafana-datasources.yml`)
- **Dashboard:** Event Management Overview (15 panels from `monitoring/grafana-dashboards/`)

**Dashboard panels:**
1. Service Status (4 panels) — health of each microservice
2. Infrastructure Status — PostgreSQL, Redis, RabbitMQ
3. Request Rate (req/s) — per-service HTTP request rate
4. Response Time — p50, p95, p99 latency
5. Error Rate — 5xx response percentage
6. CPU / Memory — per-container resource usage
7. Database connections — active connections from pool
8. Redis hit rate — cache efficiency

---

### Loki (`grafana/loki:2.9.3`)

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

Log shipper. Discovers Docker containers, reads their logs, and ships to Loki.

**Configuration:** `monitoring/promtail-config.yml`

**Discovery:** Uses Docker socket (`/var/run/docker.sock`) to find running containers and their labels.

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

### Docker Compose

```bash
docker compose -f docker-compose.yml \
               -f docker-compose.dev.yml \
               -f docker-compose.monitoring.yml \
               up --build
```

### Kubernetes

```bash
kubectl apply -f k8s/monitoring/
```

---

## Access

| Service | URL |
|---------|-----|
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 (admin/admin) |
| Loki | http://localhost:3100 |
| RabbitMQ Management | http://localhost:15672 (guest/guest) |

---

## Useful Queries

### Prometheus (PromQL)

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
