# Nginx (API Gateway)

## Overview

Nginx serves as the API gateway for the system. It handles:
1. **Reverse proxy** — Routes external requests to internal microservices
2. **Rate limiting** — Protects auth and API endpoints
3. **Static file serving** — Hosts the frontend HTML/CSS/JS
4. **Timeout management** — Prevents slow upstreams from blocking connections

| Property | Value |
|----------|-------|
| **Image** | Custom (multi-stage `nginx` build) |
| **Port** | 80 (container), 8080 (dev), 8082 (prod) |
| **Config** | `nginx/nginx.conf` |

---

## Route Mapping

| Gateway Path | Upstream Path | Service | Rate Limit |
|-------------|---------------|---------|-----------|
| `GET /health` | (inline response) | gateway | — |
| `POST /api/users/register` | `POST /users/register` | user-service | 5 req/s |
| `POST /api/users/login` | `POST /users/login` | user-service | 5 req/s |
| `* /api/users` | `* /users` | user-service | 30 req/s |
| `* /api/events` | `* /events` | event-service | 30 req/s |
| `* /api/registrations` | `* /registrations` | registration-service | 30 req/s |
| `* /api/notifications` | `* /notifications` | notification-service | 30 req/s |
| `GET /` | Static files | nginx | — |

**Priority:** More specific locations (`/api/users/login`, `/api/users/register`) match before the generic `/api/users`.

---

## Rate Limiting

```nginx
limit_req_zone $binary_remote_addr zone=api_limit:10m rate=30r/s;
limit_req_zone $binary_remote_addr zone=auth_limit:10m rate=5r/s;
```

| Zone | Rate | Burst | Applied To |
|------|------|-------|------------|
| `auth_limit` | 5 req/s | 10 (nodelay) | `/api/users/login`, `/api/users/register` |
| `api_limit` | 30 req/s | 50 (nodelay) | All other `/api/*` endpoints |

- **10m zone size:** ~160,000 unique IP addresses tracked
- **nodelay:** Processes burst requests immediately, doesn't queue them

---

## Upstream Configuration

```nginx
upstream user_service {
    server user-service:8000;
}
upstream event_service {
    server event-service:8000;
}
upstream registration_service {
    server registration-service:8000;
}
upstream notification_service {
    server notification-service:8000;
}
```

Services are referenced by Docker Compose service name. All listen on port 8000 internally.

---

## Timeouts

| Setting | Value | Purpose |
|---------|-------|---------|
| `proxy_connect_timeout` | 5s | Upstream connection timeout |
| `proxy_read_timeout` | 30s | Waiting for upstream response |
| `proxy_send_timeout` | 30s | Sending request body to upstream |
| `client_body_timeout` | 12s | Client sending request body |
| `client_header_timeout` | 12s | Client sending headers |
| `send_timeout` | 10s | Sending response to client |
| `keepalive_timeout` | 65s | Keep-alive connection timeout |

---

## Static File Caching

```nginx
location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff2?)$ {
    expires 7d;
    add_header Cache-Control "public, immutable";
}
```

---

## Proxy Headers

All proxied requests include:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
```

---

## Dockerfile

Multi-stage build that copies static assets into the nginx image:

```dockerfile
FROM nginx:alpine
COPY nginx.conf /etc/nginx/nginx.conf
COPY *.html /usr/share/nginx/html/
COPY assets/ /usr/share/nginx/html/assets/
```

---

## Health Check

The gateway health endpoint is served directly by nginx (no upstream call):

```nginx
location /health {
    add_header Content-Type application/json;
    return 200 '{"status":"gateway-healthy"}';
}
```
