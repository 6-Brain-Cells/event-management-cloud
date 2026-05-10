# Database

## Overview

All services share a single PostgreSQL 16 instance but each owns its own tables. Connection pooling is managed per-service using `psycopg2.pool.ThreadedConnectionPool`.

---

## Connection Details

| Environment | Host | Port | Database | User | Password |
|-------------|------|------|----------|------|----------|
| Development | `postgres` | 5432 | `eventdb` | `postgres` | `postgres` |
| Testing | `postgres` | 5432 | `testdb` | `postgres` | `postgres` |
| Production | `postgres` | 5432 | `eventdb_prod` | `postgres` | `${DB_PASSWORD}` |

---

## Tables

### `users` (user-service)

| Column | Type | Constraints |
|--------|------|-------------|
| id | SERIAL | PRIMARY KEY |
| username | VARCHAR(50) | UNIQUE NOT NULL |
| email | VARCHAR(100) | UNIQUE NOT NULL |
| password_hash | VARCHAR(200) | NOT NULL |
| full_name | VARCHAR(100) | |
| created_at | TIMESTAMP | DEFAULT NOW() |
| is_active | BOOLEAN | DEFAULT TRUE |

### `events` (event-service)

| Column | Type | Constraints |
|--------|------|-------------|
| id | SERIAL | PRIMARY KEY |
| title | VARCHAR(200) | NOT NULL |
| description | TEXT | |
| event_type | VARCHAR(50) | NOT NULL |
| start_date | TIMESTAMP | NOT NULL |
| end_date | TIMESTAMP | NOT NULL |
| location | VARCHAR(200) | |
| max_capacity | INT | NOT NULL DEFAULT 100 |
| registered_count | INT | DEFAULT 0 |
| organizer_id | INT | NOT NULL |
| ticket_price | DECIMAL(10,2) | DEFAULT 0.00 |
| status | VARCHAR(20) | DEFAULT 'active' |
| created_at | TIMESTAMP | DEFAULT NOW() |

### `registrations` (registration-service)

| Column | Type | Constraints |
|--------|------|-------------|
| id | SERIAL | PRIMARY KEY |
| user_id | INT | NOT NULL |
| event_id | INT | NOT NULL |
| registration_date | TIMESTAMP | DEFAULT NOW() |
| status | VARCHAR(20) | DEFAULT 'confirmed' |
| payment_method | VARCHAR(50) | DEFAULT 'free' |
| payment_status | VARCHAR(20) | DEFAULT 'pending' |
| payment_reference | VARCHAR(100) | |
| payment_gateway | VARCHAR(50) | |
| payment_processed_at | TIMESTAMP | |
| ticket_number | VARCHAR(20) | UNIQUE |
| notes | TEXT | |

**Unique constraint:** `(user_id, event_id)` — one registration per user per event.

### `notifications` (notification-service)

| Column | Type | Constraints |
|--------|------|-------------|
| id | SERIAL | PRIMARY KEY |
| user_id | INT | NOT NULL |
| title | VARCHAR(200) | NOT NULL |
| message | TEXT | |
| notification_type | VARCHAR(50) | DEFAULT 'info' |
| is_read | BOOLEAN | DEFAULT FALSE |
| created_at | TIMESTAMP | DEFAULT NOW() |

---

## Indexes

| Index | Table | Definition | Purpose |
|-------|-------|-----------|---------|
| `idx_users_email` | users | `(email) WHERE is_active=TRUE` | Login lookup, uniqueness check |
| `idx_events_status_type` | events | `(status, event_type)` | Filter active events by type |
| `idx_events_start_date` | events | `(start_date)` | Sort events by date |
| `idx_reg_user` | registrations | `(user_id)` | User's registration history |
| `idx_reg_event_status` | registrations | `(event_id, status)` | Event attendee list |
| `idx_notifications_user_read` | notifications | `(user_id, is_read)` | User notification feed |

All indexes are created via `CREATE INDEX IF NOT EXISTS` in each service's startup event, so they're auto-created on first run.

---

## Connection Pooling

Each service creates a `ThreadedConnectionPool` with the following configuration:

```python
psycopg2.pool.ThreadedConnectionPool(
    minconn=2,    # Minimum connections kept open
    maxconn=10,   # Maximum connections allowed
    host=os.getenv("DB_HOST", "postgres"),
    port=os.getenv("DB_PORT", "5432"),
    dbname=os.getenv("DB_NAME", "eventdb"),
    user=os.getenv("DB_USER", "postgres"),
    password=os.getenv("DB_PASSWORD", "postgres"),
)
```

**Why pooling?** Without pooling, each HTTP request creates a new TCP connection + PostgreSQL handshake. Pooling reuses connections, reducing latency from ~50ms to ~2ms per query.

---

## Docker Compose Configuration

```yaml
postgres:
  image: postgres:16-alpine
  environment:
    POSTGRES_DB: eventdb
    POSTGRES_USER: postgres
    POSTGRES_PASSWORD: postgres
  volumes:
    - postgres_data:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U postgres"]
    interval: 10s
    timeout: 5s
    retries: 5
```

**Volume:** `postgres_data` persists data across container restarts.

**Healthcheck:** Services wait for `postgres` to be healthy before starting (`condition: service_healthy`).

---

## Kubernetes

- **Deployment:** postgres container with resource limits
- **PVC:** `postgres-pvc` (1Gi storage)
- **Secret:** Credentials stored in Kubernetes Secret, referenced via `secretKeyRef`
- **Service:** `postgres-service` (ClusterIP) for internal access
