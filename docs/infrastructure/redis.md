# Redis

## Overview

Redis serves as a secondary pub-sub channel, token cache, and response cache for the event management system.

```mermaid
flowchart TB
    subgraph Clients["⚙️ Services"]
        US["👤 User Service"]
        ES["📅 Event Service"]
        RS["🎫 Registration Service"]
        NS["🔔 Notification Service"]
    end

    subgraph Uses["📡 Redis Usage"]
        T["🔐 Token Cache\nsession:<jwt>\nTTL: 24h"]
        C["💾 Response Cache\nevents:list:*\nTTL: 30s"]
        P["📬 Pub/Sub Channels\nuser_events, event_events\nnotification_events"]
    end

    subgraph Redis["📡 Redis :6379"]
        RD["redis:7-alpine\nAOF persistence\nappendonly yes"]
    end

    US --> T
    ES --> C
    RS --> P
    US --> P
    ES --> P

    T & C & P --> RD

    style Redis fill:#16213e,stroke:#e94560,color:#e94560
    style Clients fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Uses fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

| Property | Value |
|----------|-------|
| **Image** | `redis:7-alpine` |
| **Port** | 6379 |
| **Persistence** | AOF (appendonly yes) |
| **Volume** | `redis_data` |

---

## Usage Patterns

### Token Storage (user-service)

```mermaid
flowchart TB
    LOGIN["Login → JWT token generated"]
    STORE["Redis: SETEX session:<jwt> 86400 {user_data}"]
    LOOKUP["Subsequent requests → Authorization: Bearer <jwt>"]
    CHECK["Check Redis: GET session:<jwt>"]
    VALID{"Found?"}
    VALID -->|"Yes"| NEXT["✅ Proceed with request"]
    VALID -->|"No"| REJECT["❌ Reject (token expired/invalid)"]

    LOGIN --> STORE --> LOOKUP --> CHECK --> VALID

    style LOGIN fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style STORE fill:#16213e,stroke:#e94560,color:#e94560
    style VALID fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

After login, the user-service stores the JWT token in Redis with a 24-hour TTL:

```python
r = get_redis()
r.setex(f"session:{token}", 86400, json.dumps(dict(user)))
```

Note: Key prefix changed from `token:` to `session:`, and the token is now a JWT (not random hex).

### Pub-Sub Publishing

```mermaid
flowchart TB
    subgraph Channels["📡 Redis Pub/Sub Channels"]
        CH1["user_events\n(published by: user-service)"]
        CH2["event_events\n(published by: event-service)"]
        CH3["notification_events\n(published by: registration-service)"]
    end

    subgraph Note["ℹ️ Note"]
        N["notification-service does NOT subscribe\n(only RabbitMQ) to avoid duplicate notifications"]
    end

    CH1 & CH2 & CH3 -.backup.-> N

    style Channels fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Note fill:#16213e,stroke:#e94560,color:#e94560
```

| Service | Channel | Event |
|---------|---------|-------|
| user-service | `user_events` | `user_registered` |
| event-service | `event_events` | `event_created` |
| registration-service | `notification_events` | `registration_confirmed`, `registration_cancelled` |

**Note:** The notification-service does NOT subscribe to Redis channels — it only consumes from RabbitMQ to prevent duplicate notifications.

### Event Listing Cache

```mermaid
flowchart TB
    subgraph Request["📥 GET /events Request"]
        R1["Build cache key:\nevents:list:{status}:{type}:{page}:{size}"]
        R2["Check Redis"]
    end

    subgraph HIT["✅ Cache Hit"]
        H1["Return cached JSON"]
        H2["No DB query"]
    end

    subgraph MISS["❌ Cache Miss"]
        M1["Query PostgreSQL"]
        M2["Store in Redis (30s TTL)"]
        M3["Return response"]
    end

    subgraph INV["🗑️ Invalidation on Write"]
        W1["POST /events, PUT /events/{id}, DELETE /events/{id}"]
        W2["DELETE events:list:*"]
    end

    R1 --> R2 --> HIT & MISS
    W1 --> W2

    style Request fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style HIT fill:#0f3460,stroke:#00d9ff,color:#00d9ff
    style MISS fill:#16213e,stroke:#e94560,color:#e94560
    style INV fill:#16213e,stroke:#e94560,color:#e94560
```

The event service caches `GET /events` responses in Redis to reduce database load on high-traffic list endpoints.

**Cache Key Format:**
```
events:list:{status}:{event_type}:{page}:{page_size}
```

**Examples:**
- `events:list:active:conference:1:20` — Active conferences, page 1
- `events:list:all::1:10` — All events (super_admin), page 1

**Configuration:**

| Setting | Value | Notes |
|---------|-------|-------|
| TTL | 30 seconds | Configurable via `CACHE_TTL` env var |
| Invalidation | On write | Cache keys are deleted on event create, update, or delete |
| Fallback | Direct DB query | If Redis is unavailable, the endpoint queries PostgreSQL directly |

**Behavior:**
1. On `GET /events`, the service builds the cache key from query parameters
2. If the key exists in Redis, the cached JSON is returned immediately
3. If the key is missing, the service queries PostgreSQL and stores the result with TTL
4. On `POST /events`, `PUT /events/{id}`, or `DELETE /events/{id}`, all `events:list:*` keys matching the pattern are invalidated

---

## Connection Configuration

```mermaid
flowchart TB
    subgraph Singleton["📦 Redis Singleton (per service)"]
        GET["get_redis()"]
        CHECK{_redis_client is None?}
        CREATE["redis.Redis(\nhost, port,\ndecode_responses=True,\nsocket_timeout=5s,\nretry_on_timeout=True)"]
        RETURN["Return singleton"]
    end

    GET --> CHECK
    CHECK -->|"Yes"| CREATE --> RETURN
    CHECK -->|"No"| RETURN

    style Singleton fill:#16213e,stroke:#e94560,color:#e94560
```

Each service creates a Redis singleton:

```python
def get_redis():
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "redis"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5,
            retry_on_timeout=True,
        )
    return _redis_client
```

**Timeouts:** 5-second connect/read timeout prevents hanging on Redis failure.

**Error handling:** All Redis operations are wrapped in `try/except` — failures are silent and don't affect core functionality.

---

## Docker Compose

```yaml
redis:
  image: redis:7-alpine
  command: redis-server --appendonly yes
  volumes:
    - redis_data:/data
  healthcheck:
    test: ["CMD", "redis-cli", "ping"]
    interval: 10s
    timeout: 5s
    retries: 5
```

**AOF persistence:** `--appendonly yes` ensures data survives container restarts.

---

## Production Configuration

```yaml
redis:
  command: redis-server --appendonly yes --requirepass ${REDIS_PASSWORD:-changeme_in_prod}
```

Password authentication enabled in production. Services pass `REDIS_PASSWORD` via environment variables.

---

## Monitoring

```mermaid
flowchart TB
    subgraph Exporters["📊 Prometheus Exporters"]
        RE["📡 redis_exporter\n:v1.55.0 :9121"]
        NE["🖥️ node-exporter\n:v1.7.0 :9100"]
    end

    subgraph Prometheus["📊 Prometheus"]
        P["Scrape targets:\nredis_exporter :9121\nnode_exporter :9100"]
    end

    subgraph Grafana["📈 Grafana"]
        G["Redis Dashboard\n(memory, keys, hit rate)"]
    end

    RE & NE --> P --> G

    style Exporters fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Prometheus fill:#16213e,stroke:#e94560,color:#e94560
    style Grafana fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

- **Redis Exporter:** `oliver006/redis_exporter:v1.55.0` exposes metrics at `:9121`
- **Prometheus scrapes:** `http://redis-exporter:9121/metrics`
- **Grafana dashboard:** Redis metrics included in the overview dashboard

---

## Kubernetes

```mermaid
flowchart TB
    subgraph K8s["☸️ Kubernetes"]
        subgraph Deploy["📦 Deployments"]
            D1["redis Deployment\n(replicas: 1)"]
        end

        subgraph Storage["💾 Persistent Storage"]
            PVC["redis-pvc\n(512Mi, ReadWriteOnce)"]
        end

        subgraph Svc["🔌 Services"]
            SVC["redis-service\n(ClusterIP :6379)"]
        end

        subgraph Sec["🔐 Secrets"]
            SEC["event-mgmt-secrets\n(REDIS_PASSWORD via secretKeyRef)"]
        end

        D1 --> PVC
        D1 --> SVC
        D1 -.envFrom.-> SEC
    end

    style K8s fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Deploy fill:#16213e,stroke:#e94560,color:#e94560
    style Storage fill:#0f3460,stroke:#00d9ff,color:#00d9ff
    style Svc fill:#16213e,stroke:#e94560,color:#e94560
    style Sec fill:#0f3460,stroke:#e94560,color:#e94560
```

- **Deployment:** Redis container with resource limits
- **PVC:** `redis-pvc` (512Mi storage)
- **Secret:** Password stored in Kubernetes Secret