# EventHub — Event Management System

A cloud-native microservices platform for managing conferences, workshops, and seminars.
Built with Docker, Docker Compose (dev / test / prod environments), and Kubernetes (Minikube).

---

## Architecture

```text
                    ┌──────────────────────────────────────────┐
                    │         Nginx API Gateway (:80)          │
                    └──────┬──────────┬──────────┬────────────┘
                           │          │          │          │
              ┌────────────▼─┐  ┌─────▼────┐  ┌─▼──────────┐  ┌──────────▼───┐
              │ User Service │  │  Event   │  │Registration│  │Notification  │
              │   :8001      │  │ Service  │  │  Service   │  │  Service     │
              │   FastAPI    │  │  :8002   │  │   :8003    │  │   :8004      │
              └──────┬───────┘  └────┬─────┘  └─────┬──────┘  └──────┬───────┘
                     │               │               │  Redis Pub/Sub  │
                     └───────────────┴──────────┬────┘◄───────────────┘
                                                │
                              ┌─────────────────┼──────────────────┐
                              │                 │                  │
                        ┌─────▼──────┐    ┌─────▼──────┐
                        │ PostgreSQL │    │   Redis    │
                        │   :5432    │    │   :6379    │
                        └────────────┘    └────────────┘

         Monitoring (bonus): Prometheus :9090 · Grafana :3000 · Node Exporter :9100
```

### Services

| Service | Port | Responsibility |
| --- | --- | --- |
| **user-service** | 8001 | Registration, login, user profiles, token auth via Redis |
| **event-service** | 8002 | Create/manage events, schedules, capacity |
| **registration-service** | 8003 | Event bookings, ticket generation, mock payment processing |
| **notification-service** | 8004 | Reminders, async event handling via Redis Pub/Sub |
| **nginx** | 80 | API gateway + serves frontend dashboard |
| **postgres** | 5432 | Primary relational database |
| **redis** | 6379 | Cache + async message broker (Pub/Sub) |

---

## Project Structure

```text
event-management-system/
├── manage.sh                        ← one-command environment manager
├── docker-compose.yml               ← base shared definitions
├── docker-compose.dev.yml           ← development overrides
├── docker-compose.test.yml          ← testing overrides + test-runner
├── docker-compose.prod.yml          ← production overrides
├── docker-compose.monitoring.yml    ← bonus: Prometheus + Grafana
├── services/
│   ├── user-service/
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── Dockerfile               ← multi-stage optimized build
│   ├── event-service/
│   ├── registration-service/
│   └── notification-service/
├── nginx/
│   ├── nginx.conf                   ← reverse proxy + routing rules
│   ├── index.html                   ← frontend dashboard
│   └── Dockerfile
├── k8s/
│   ├── configmaps/config.yaml
│   ├── deployments/deployments.yaml
│   └── services/services.yaml
├── monitoring/
│   └── prometheus.yml
└── tests/
    ├── test_api.py
    └── test_payment.py
```

---

## Docker Images Used

| Image | Purpose |
| --- | --- |
| `python:3.11-slim` | Base for all FastAPI services (multi-stage build) |
| `nginx:1.25-alpine` | API gateway + frontend |
| `postgres:16-alpine` | Primary database |
| `redis:7-alpine` | Cache + message broker |
| `prom/prometheus` | Metrics collection (bonus) |
| `grafana/grafana` | Dashboards (bonus) |
| `prom/node-exporter` | Host metrics (bonus) |

All service images use multi-stage builds to minimize final image size (~80–100 MB each).

---

## Native Ubuntu Setup Guide

The project runs natively on Linux.

### 1. Install Docker and Docker Compose

If you haven't already, install Docker on your Ubuntu system:

```bash
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo \"$VERSION_CODENAME\") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update

# Install the Docker packages
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
```

### 2. Manage Docker as a non-root user

To run docker without `sudo`:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

Verify Docker works by running:

```bash
docker ps
```

Expected output: an empty table with no errors.

### 3. Navigate to the project and run it

Open your terminal and navigate to where you extracted or cloned the project:

```bash
cd event-management-system
chmod +x manage.sh
./manage.sh up dev
```

The first run takes a few minutes while Docker builds all images.
When you see:

```text
✅  dev environment running:
   Frontend:    http://localhost:8080
```

Open `http://localhost:8080` in your browser.

---

## Running the Project

### Development environment (port 8080)

```bash
./manage.sh up dev
```

- Hot-reload enabled — code changes apply without rebuilding
- PostgreSQL (:5432) and Redis (:6379) ports exposed for local tools
- Each service directly accessible on ports 8001–8004
- Debug logging enabled

```bash
# With Prometheus + Grafana monitoring (bonus):
./manage.sh up dev --monitor
```

### Testing environment (port 8081)

Uses an isolated `testdb` database so tests never pollute development data.
The `test-runner` container runs the full pytest suite automatically and exits.

```bash
./manage.sh test
```

### Production environment (port 8082)

```bash
# Create secrets file first:
echo "DB_PASSWORD=your_secure_password" > .env
echo "REDIS_PASSWORD=your_redis_password" >> .env

./manage.sh up prod
```

Production differences from dev:

- No exposed DB or Redis ports
- CPU and memory limits enforced per container
- `restart: always` policies
- `user-service` and `event-service` are scaled to 2 replicas by `manage.sh up prod` using `docker compose --scale`

### Running all three environments simultaneously

All three environments use different ports and isolated volumes, so they can run on
the same machine at the same time:

```bash
./manage.sh up dev &
./manage.sh up test &
./manage.sh up prod
# Dev: :8080 | Test: :8081 | Prod: :8082
```

### Stopping

```bash
./manage.sh down dev     # stop dev
./manage.sh down prod    # stop prod
./manage.sh clean        # stop everything and wipe all volumes
```

---

## API Reference

All routes go through the Nginx gateway. Replace `8080` with `8081`/`8082` for
test/prod environments.

### User Service — `http://localhost:8080/api/users`

```text
POST   /api/users/register          Register a new user
POST   /api/users/login             Login → returns session token (stored in Redis)
GET    /api/users                   List all active users
GET    /api/users/{id}              Get user by ID
DELETE /api/users/{id}              Deactivate user
```

### Event Service — `http://localhost:8080/api/events`

```text
POST   /api/events                  Create a new event
GET    /api/events                  List events  (?event_type=conference|workshop|seminar)
GET    /api/events/{id}             Get event details
PUT    /api/events/{id}             Update event fields
DELETE /api/events/{id}             Cancel event (sets status=cancelled)
```

### Registration Service — `http://localhost:8080/api/registrations`

```text
POST   /api/registrations           Register for event → returns ticket number
GET    /api/registrations/{id}      Get registration by ID
GET    /api/registrations/user/{id} All registrations for a user
GET    /api/registrations/event/{id} All confirmed attendees for an event
PATCH  /api/registrations/{id}/payment  Update payment status
POST   /api/registrations/{id}/process-payment  Process payment with simulated gateway
DELETE /api/registrations/{id}      Cancel registration
```

Payment processing notes:

- Registrations now run through a simulated gateway flow (`free`, `card`, `paypal`, `bank_transfer`)
- Paid registrations store `payment_reference`, `payment_gateway`, and `payment_processed_at`
- This satisfies payment-processing behavior without relying on external provider credentials

### Notification Service — `http://localhost:8080/api/notifications`

```text
POST   /api/notifications           Send a manual notification
GET    /api/notifications/user/{id} Get all notifications for a user
PATCH  /api/notifications/{id}/read Mark notification as read
POST   /api/notifications/broadcast Send to multiple users
```

---

## Kubernetes (Minikube)

Minikube is the lightweight local Kubernetes option. Using `--driver=docker` runs the
entire cluster inside a Docker container instead of a VM — much easier on older hardware.

```bash
# Install Minikube
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
sudo snap install kubectl --classic

# Start cluster (lightweight settings)
minikube start --driver=docker --cpus=2 --memory=2048

# Build images inside Minikube's Docker daemon and deploy
./manage.sh k8s-up

# Get the URL to open in your browser
minikube service nginx --url

# Useful kubectl commands
kubectl get pods
kubectl get services
kubectl logs deployment/user-service
kubectl scale deployment event-service --replicas=3

# Tear down
./manage.sh k8s-down
minikube stop
```

---

## Monitoring (Bonus)

Add the full monitoring stack to any environment:

```bash
./manage.sh up dev --monitor

# Prometheus:  http://localhost:9090
# Grafana:     http://localhost:3000  (login: admin / admin)
```

**Grafana quick setup:**

1. Add data source: Prometheus → URL: `http://prometheus:9090`
2. Import dashboard **1860** — Node Exporter Full (host metrics)
3. Import dashboard **9628** — PostgreSQL metrics

---

## Async Communication (Bonus)

The system uses **Redis Pub/Sub** for decoupled async messaging between services.
No service calls another directly for notifications — they publish an event and move on.

| Channel | Published by | Consumed by | When |
| --- | --- | --- | --- |
| `notification_events` | Registration Service | Notification Service | User registers for an event |
| `user_events` | User Service | Notification Service | New user account created |
| `event_events` | Event Service | Notification Service | New event created |

The notification service runs a background thread that subscribes to all three channels
and automatically stores the appropriate notification when any event arrives.

Reminders and updates are user-visible in-app by default, with optional webhook
forwarding by setting `NOTIFICATION_WEBHOOK_URL`.

To watch it live:

```bash
docker exec -it event-management-system-redis-1 redis-cli subscribe notification_events
```

---

## Useful Commands

```bash
# Check all running containers and their ports
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# View logs for a specific service
docker logs event-management-system-nginx-1
docker logs event-management-system-user-service-1 --follow

# Open a psql shell directly
docker exec -it event-management-system-postgres-1 psql -U postgres -d eventdb

# Open Redis CLI
docker exec -it event-management-system-redis-1 redis-cli

# Monitor resource usage
docker stats

# Rebuild a single service without restarting everything
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d user-service
```

---

## CI/CD

Minimal CI is configured in `.github/workflows/ci.yml`.

- Triggers on push and pull request
- Uses GitHub Actions runner `ubuntu-latest`
- Runs `./manage.sh test` to validate integration tests before merge

---

## Debugging & Known Issues

### Issue 1 — nginx crashes: "unknown $remote_method variable"

**Symptom:** After `./manage.sh up dev`, nginx is missing from `docker ps`.
Port 8080 is unreachable. Running `docker logs event-management-system-nginx-1` shows:

```text
[emerg] 1#1: unknown "remote_method" variable
```

**Cause:** Typo in `nginx/nginx.conf`. The variable `$remote_method` does not exist
in nginx.

**Fix:** In `nginx/nginx.conf` change:

```nginx
'$remote_addr - $remote_method [$time_local] "$request" '
```

to:

```nginx
'$remote_addr - $request_method [$time_local] "$request" '
```

Then rebuild only nginx (no need to restart other containers):

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d nginx
```

---

### Issue 2 — Dashboard shows "error 422" / "error 404" for all services

**Symptom:** The frontend loads at `http://localhost:8080` but all four service
health badges show red errors.

**Cause:** The health check URLs in `nginx/index.html` were routing through the Nginx
proxy (e.g. `/api/users/health` → `/users/health` on the service) which does not exist.
The correct health endpoint on each service is `/health` at the root.

**Fix:** In `nginx/index.html` find the SERVICES array and change it to hit each
service directly on its exposed dev port:

```javascript
const SERVICES = [
  { name: 'User Service',          url: 'http://localhost:8001/health', display: ':8001' },
  { name: 'Event Service',         url: 'http://localhost:8002/health', display: ':8002' },
  { name: 'Registration Service',  url: 'http://localhost:8003/health', display: ':8003' },
  { name: 'Notification Service',  url: 'http://localhost:8004/health', display: ':8004' },
];
```

Then rebuild nginx:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build -d nginx
```

### General troubleshooting tips

**Services show "unreachable" right after startup** — the containers are still
initializing. Wait 30 seconds and refresh the browser.

**Port already in use** — something else is using 8080. Run `./manage.sh down dev`,
wait a few seconds, then `./manage.sh up dev` again.

**Containers crash or restart repeatedly** — likely an out-of-memory situation on
an older laptop. Close Chrome and other heavy apps, then:

```bash
./manage.sh down dev
./manage.sh up dev
```

**Full reset — wipe everything and start clean:**

```bash
./manage.sh clean
./manage.sh up dev
```
