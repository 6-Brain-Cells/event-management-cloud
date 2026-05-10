# EventHub — Event Management System

A cloud-native microservices platform for managing conferences, workshops, and seminars.
Built with Docker, Docker Compose (dev / test / prod environments), and Kubernetes (Minikube).

---

## Architecture

```
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

         Monitoring: Prometheus :9090 · Grafana :3000 · Node Exporter :9100
         Logging:    Promtail (log agent) → Loki :3100 → Grafana Explore
```

### Services

| Service | Port | Responsibility |
|---|---|---|
| **user-service** | 8001 | Registration, login, user profiles, token auth via Redis |
| **event-service** | 8002 | Create/manage events, schedules, capacity |
| **registration-service** | 8003 | Event bookings, ticket generation, payment status |
| **notification-service** | 8004 | Reminders, async event handling via Redis Pub/Sub |
| **nginx** | 80 | API gateway + serves frontend dashboard |
| **postgres** | 5432 | Primary relational database |
| **redis** | 6379 | Cache + async message broker (Pub/Sub) |
| **prometheus** | 9090 | Metrics scraping and storage (bonus) |
| **loki** | 3100 | Centralized log storage (bonus) |
| **promtail** | 9080 | Log collection agent — ships container logs to Loki (bonus) |
| **grafana** | 3000 | Unified metrics + logs dashboard (bonus) |

---

## Project Structure

```
event-management-system/
├── manage.sh                        ← one-command environment manager
├── docker-compose.yml               ← base shared definitions
├── docker-compose.dev.yml           ← development overrides
├── docker-compose.test.yml          ← testing overrides + test-runner
├── docker-compose.prod.yml          ← production overrides
├── docker-compose.monitoring.yml    ← bonus: Prometheus + Grafana + Loki + Promtail
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
│   ├── services/services.yaml
│   └── monitoring/
│       ├── loki-deployment.yaml     ← Loki log store (Deployment + Service)
│       └── promtail-daemonset.yaml  ← Promtail log agent (DaemonSet + RBAC)
├── monitoring/
│   ├── prometheus.yml               ← Prometheus scrape config
│   ├── loki-config.yml              ← Loki server config (filesystem storage)
│   ├── promtail-config.yml          ← Promtail Docker discovery pipeline
│   └── grafana-datasources.yml      ← Grafana auto-provisioning (Prometheus + Loki)
└── tests/
    └── test_api.py
```

---

## Docker Images Used

| Image | Purpose |
|---|---|
| `python:3.11-slim` | Base for all FastAPI services (multi-stage build) |
| `nginx:1.25-alpine` | API gateway + frontend |
| `postgres:16-alpine` | Primary database |
| `redis:7-alpine` | Cache + message broker |
| `prom/prometheus` | Metrics collection (bonus) |
| `prom/node-exporter` | Host metrics (bonus) |
| `prometheuscommunity/postgres-exporter` | PostgreSQL metrics (bonus) |
| `oliver006/redis_exporter` | Redis metrics (bonus) |
| `grafana/loki` | Centralized log storage (bonus) |
| `grafana/promtail` | Log collection agent — reads Docker container logs (bonus) |
| `grafana/grafana` | Unified metrics + logs dashboards (bonus) |

All service images use multi-stage builds to minimize final image size (~80–100 MB each).

---

## Windows Setup Guide (WSL2 + Docker Desktop)

The project runs on Linux. On Windows, WSL2 provides a real Linux kernel that fully
satisfies the "Linux machine" requirement — `uname -a` inside it shows a Linux kernel.

### 1. Install WSL2

Open PowerShell as Administrator:

```powershell
wsl --install
```

Restart your PC when prompted. After restart Ubuntu opens automatically — set a username
and password when asked.

> **Note:** After the restart you will land directly inside the Ubuntu terminal.
> `wsl --shutdown` is a PowerShell command — if you need to run it, type `exit` first
> to leave Ubuntu, then run it in PowerShell.

### 2. Connect Docker Desktop to WSL2

Open Docker Desktop → ⚙️ Settings → Resources → WSL Integration:

- "Enable integration with my default WSL distro" → **ON**
- Toggle Ubuntu → **ON**

Click **Apply & Restart**.

### 3. Limit RAM (important for older / slower laptops)

In PowerShell:

```powershell
notepad "$env:USERPROFILE\.wslconfig"
```

Paste this, save, and close Notepad:

```ini
[wsl2]
memory=3GB
processors=2
swap=1GB
```

Then shut down WSL so the limits apply on next launch:

```powershell
wsl --shutdown
```

### 4. Open Ubuntu and verify Docker works

Search **Ubuntu** in the Start menu and open it. You should see a prompt like
`user@LAPTOP:~$`. Run:

```bash
docker ps
```

Expected output: an empty table with no errors. If you get a permission error run:

```bash
sudo usermod -aG docker $USER
newgrp docker
```

### 5. Copy the project into WSL2 and run it

Windows drives are mounted under `/mnt/` in WSL2. For example `E:\cloud\` becomes
`/mnt/e/cloud/`. Adjust the path below to wherever you extracted the project:

```bash
cp /mnt/e/cloud/event-management-system.tar.gz ~/
cd ~
tar -xzf event-management-system.tar.gz
cd event-management-system
chmod +x manage.sh
./manage.sh up dev
```

The first run takes 5–10 minutes on a slow laptop while Docker builds all images.
When you see:

```
✅  dev environment running:
   Frontend:    http://localhost:8080
```

Open `http://localhost:8080` in your **Windows** browser (Chrome, Edge, etc.).
WSL2 automatically forwards ports to Windows so localhost works from either side.

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
- 2 replicas of user-service and event-service

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

```
POST   /api/users/register          Register a new user
POST   /api/users/login             Login → returns session token (stored in Redis)
GET    /api/users                   List all active users
GET    /api/users/{id}              Get user by ID
DELETE /api/users/{id}              Deactivate user
```

### Event Service — `http://localhost:8080/api/events`

```
POST   /api/events                  Create a new event
GET    /api/events                  List events  (?event_type=conference|workshop|seminar)
GET    /api/events/{id}             Get event details
PUT    /api/events/{id}             Update event fields
DELETE /api/events/{id}             Cancel event (sets status=cancelled)
```

### Registration Service — `http://localhost:8080/api/registrations`

```
POST   /api/registrations           Register for event → returns ticket number
GET    /api/registrations/{id}      Get registration by ID
GET    /api/registrations/user/{id} All registrations for a user
GET    /api/registrations/event/{id} All confirmed attendees for an event
PATCH  /api/registrations/{id}/payment  Update payment status
DELETE /api/registrations/{id}      Cancel registration
```

### Notification Service — `http://localhost:8080/api/notifications`

```
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
# Install Minikube inside WSL2
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
# Loki:        http://localhost:3100  (log storage API)
# Promtail:    http://localhost:9080  (shipper health)
```

**Grafana is auto-configured** — both Prometheus and Loki data sources are provisioned automatically on first start. No manual setup required.

**Grafana quick setup for dashboards:**
1. Go to **Dashboards → Import** → ID `1860` — Node Exporter Full (host metrics)
2. Go to **Dashboards → Import** → ID `9628` — PostgreSQL metrics

---

## Centralized Logging (Bonus)

All container logs are automatically collected by **Promtail** and stored in **Loki**.
You can query them from the **Grafana Explore** tab using **LogQL**.

### Start the logging stack

```bash
./manage.sh up dev --monitor
# Promtail discovers all containers on event-network automatically
# No code changes needed in any service
```

### Query logs in Grafana

1. Open **http://localhost:3000** (admin / admin)
2. Go to **Explore** (compass icon in left sidebar)
3. Select **Loki** as the data source
4. Use **LogQL** to query:

```logql
# All logs from the user service
{service="user-service"}

# All logs from all microservices
{service=~"user-service|event-service|registration-service|notification-service"}

# Filter for errors only
{service="registration-service"} |= "ERROR"

# Nginx access logs, 5xx errors only
{service="nginx"} | status >= 500

# Count log lines per service over time (rate)
sum by (service) (rate({service=~".+"}[5m]))
```

### Log pipeline

```
Docker container stdout/stderr
        │
        ▼
   Promtail (:9080)          ← discovers containers via /var/run/docker.sock
   labels: service, container_name, stream
        │  HTTP push
        ▼
   Loki (:3100)              ← stores logs on filesystem (/loki)
        │  LogQL
        ▼
   Grafana (:3000)           ← Explore → Loki data source
```

### Kubernetes logging

When deployed via Minikube, Promtail runs as a **DaemonSet** (one pod per node):

```bash
./manage.sh k8s-up

# Access Grafana for logs:
kubectl port-forward svc/grafana 3000:3000

# Check Promtail is shipping logs:
kubectl logs daemonset/promtail

# Check Loki health:
kubectl port-forward svc/loki 3100:3100
curl http://localhost:3100/ready
```

---

## Async Communication (Bonus)

The system uses **Redis Pub/Sub** for decoupled async messaging between services.
No service calls another directly for notifications — they publish an event and move on.

| Channel | Published by | Consumed by | When |
|---|---|---|---|
| `notification_events` | Registration Service | Notification Service | User registers for an event |
| `user_events` | User Service | Notification Service | New user account created |
| `event_events` | Event Service | Notification Service | New event created |

The notification service runs a background thread that subscribes to all three channels
and automatically stores the appropriate notification when any event arrives.

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

## Debugging & Known Issues

### Issue 1 — nginx crashes: "unknown $remote_method variable"

**Symptom:** After `./manage.sh up dev`, nginx is missing from `docker ps`.
Port 8080 is unreachable. Running `docker logs event-management-system-nginx-1` shows:

```
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

---

### Issue 3 — "wsl: command not found" in Ubuntu terminal

**Cause:** `wsl --shutdown` is a PowerShell/Windows command. Running it inside the
Ubuntu terminal doesn't work.

**Fix:** Type `exit` to leave Ubuntu and return to PowerShell, then run the command there.

---

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