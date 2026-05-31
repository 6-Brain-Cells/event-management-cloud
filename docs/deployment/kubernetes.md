# Kubernetes Deployment

## Overview

The project includes Kubernetes manifests for deploying the full stack to a Minikube cluster. All images use `imagePullPolicy: Never` — they must be built inside Minikube's Docker daemon.

```mermaid
flowchart TB
    subgraph K8s["☸️ Kubernetes Cluster"]
        subgraph Nodes["👤 Nodes"]
            N1["Minikube Node\n(Docker driver)"]
        end

        subgraph Pods["📦 Pods"]
            P1["user-service (×2)"]
            P2["event-service (×2)"]
            P3["registration-service (×2)"]
            P4["notification-service (×1)"]
            P5["postgres (×1)"]
            P6["redis (×1)"]
            P7["rabbitmq (×1)"]
            P8["nginx (×1)"]
            P9["prometheus (×1)"]
            P10["grafana (×1)"]
            P11["loki (×1)"]
            P12["promtail (DaemonSet)"]
        end

        subgraph Services["🔌 Services"]
            S1["ClusterIP (internal)"]
            S2["NodePort (nginx :30080)"]
        end

        subgraph Storage["💾 PVCs"]
            PVC1["postgres-pvc (1Gi)"]
            PVC2["redis-pvc (512Mi)"]
        end

        N1 --> Pods
        Pods --> Services
        P5 --> PVC1
        P6 --> PVC2
    end

    style K8s fill:#16213e,stroke:#e94560,color:#e94560
```

---

## Quick Start

```mermaid
flowchart TB
    subgraph Steps["⚡ Deployment Steps"]
        S1["minikube start\n--driver=docker --cpus=2 --memory=2048"]
        S2["eval $(minikube docker-env)"]
        S3["docker build ... (build images inside Minikube)"]
        S4["kubectl apply -f k8s/configmaps/"]
        S5["kubectl apply -f k8s/services/"]
        S6["kubectl apply -f k8s/deployments/"]
        S7["kubectl apply -f k8s/monitoring/"]
        S8["minikube service nginx --url"]
    end

    S1 --> S2 --> S3 --> S4 --> S5 --> S6 --> S7 --> S8

    style Steps fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
```

### Using manage.sh

```bash
./manage.sh k8s-up
```

### Manual

```bash
# Start Minikube
minikube start --memory=8192 --cpus=4

# Use Minikube's Docker daemon
eval $(minikube docker-env)

# Build all images inside Minikube
docker build -t event-mgmt/user-service:latest ./services/user-service
docker build -t event-mgmt/event-service:latest ./services/event-service
docker build -t event-mgmt/registration-service:latest ./services/registration-service
docker build -t event-mgmt/notification-service:latest ./services/notification-service
docker build -t event-mgmt/nginx:latest ./nginx

# Apply manifests in order
kubectl apply -f k8s/configmaps/
kubectl apply -f k8s/services/
kubectl apply -f k8s/deployments/
kubectl apply -f k8s/monitoring/

# Wait for pods
kubectl get pods -w

# Access the app
minikube service nginx --url
```

---

## Directory Structure

```mermaid
flowchart TB
    subgraph K8s["k8s/"]
        D1["configmaps/\nconfig.yaml"]
        D2["deployments/\ndeployments.yaml"]
        D3["services/\nservices.yaml"]
        D4["monitoring/\nprometheus-deployment.yaml\ngrafana-deployment.yaml\nloki-deployment.yaml\npromtail-daemonset.yaml"]
        D5["argocd/\napplication.yaml"]
    end

    style K8s fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style D1 fill:#16213e,stroke:#e94560,color:#e94560
    style D2 fill:#16213e,stroke:#e94560,color:#e94560
    style D3 fill:#16213e,stroke:#e94560,color:#e94560
    style D4 fill:#0f3460,stroke:#00d9ff,color:#00d9ff
    style D5 fill:#0f3460,stroke:#e94560,color:#e94560
```

```
k8s/
├── configmaps/
│   └── config.yaml            # ConfigMap + Secret
├── deployments/
│   └── deployments.yaml       # 8 Deployments + 1 DaemonSet + 2 PVCs
├── services/
│   └── services.yaml          # 8 Services (ClusterIP + NodePort)
└── monitoring/
    ├── prometheus-deployment.yaml
    ├── grafana-deployment.yaml
    ├── loki-deployment.yaml
    └── promtail-daemonset.yaml
```

---

## Resources Summary

| Resource | Count | Details |
|----------|-------|---------|
| **Deployments** | 8 | user-service(2), event-service(2), registration-service(2), notification-service(1), postgres(1), redis(1), rabbitmq(1), nginx(1) |
| **DaemonSets** | 1 | promtail (log collection on every node) |
| **Services** | 8 | ClusterIP (internal) + NodePort (nginx) |
| **ConfigMaps** | 1 | Application configuration (DB host, ports, service URLs) |
| **Secrets** | 1 | `event-mgmt-secrets` — DB password, Redis password, RabbitMQ credentials |
| **PVCs** | 2 | postgres (1Gi), redis (512Mi) |
| **ServiceAccounts** | 1 | prometheus |
| **ClusterRoles** | 1 | prometheus (kube-api read access) |
| **ClusterRoleBindings** | 1 | prometheus ↔ ServiceAccount |

---

## Configuration

```mermaid
flowchart TB
    subgraph ConfigMap["📋 event-mgmt-config (ConfigMap)"]
        C1["DB_HOST, DB_PORT, DB_NAME, DB_USER"]
        C2["REDIS_HOST, REDIS_PORT"]
        C3["RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER"]
        C4["EVENT_SERVICE_URL"]
    end

    subgraph Secret["🔐 event-mgmt-secrets (Secret)"]
        S1["DB_PASSWORD"]
        S2["REDIS_PASSWORD"]
        S3["RABBITMQ_PASSWORD"]
    end

    subgraph Usage["📦 Used By"]
        U1["All app Deployments: envFrom configMapRef + secretKeyRef"]
    end

    ConfigMap & Secret --> U1

    style ConfigMap fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Secret fill:#0f3460,stroke:#e94560,color:#e94560
    style Usage fill:#16213e,stroke:#e94560,color:#e94560
```

### ConfigMap (`k8s/configmaps/config.yaml`)

Name: `event-mgmt-config`

Contains non-sensitive configuration.

### Secret (`k8s/configmaps/config.yaml`)

Name: `event-mgmt-secrets`

Contains sensitive credentials.

---

## Services

| Service | Type | Port | Target |
|---------|------|------|--------|
| postgres | ClusterIP | 5432 | postgres:5432 |
| redis | ClusterIP | 6379 | redis:6379 |
| rabbitmq | ClusterIP | 5672, 15672 | rabbitmq:5672, rabbitmq:15672 |
| user-service | ClusterIP | 8000 | user-service:8000 |
| event-service | ClusterIP | 8000 | event-service:8000 |
| registration-service | ClusterIP | 8000 | registration-service:8000 |
| notification-service | ClusterIP | 8000 | notification-service:8000 |
| nginx | NodePort | 80 → 30080 | nginx:80 |

All services use Kubernetes DNS names for internal communication (e.g., `postgres:5432`, `event-service:8000`).

---

## Deployments

### Replicas & Resources

| Deployment | Replicas | CPU Request/Limit | Memory Request/Limit |
|------------|----------|-------------------|---------------------|
| user-service | 2 | 100m / 500m | 128Mi / 256Mi |
| event-service | 2 | 100m / 500m | 128Mi / 256Mi |
| registration-service | 2 | 100m / 500m | 128Mi / 256Mi |
| notification-service | 1 | 50m / 250m | 64Mi / 128Mi |
| postgres | 1 | 100m / 500m | 128Mi / 512Mi |
| redis | 1 | 50m / 250m | 64Mi / 256Mi |
| rabbitmq | 1 | 100m / 500m | 256Mi / 512Mi |
| nginx | 1 | 50m / 200m | 32Mi / 64Mi |

### Readiness Probes

| Service | Type | Path/Command | Initial Delay | Period |
|---------|------|-------------|---------------|--------|
| user-service | HTTP GET | `/health` on :8000 | 15s | 10s |
| event-service | HTTP GET | `/health` on :8000 | 15s | 10s |
| registration-service | HTTP GET | `/health` on :8000 | 15s | 10s |
| notification-service | HTTP GET | `/health` on :8000 | 15s | 10s |
| nginx | HTTP GET | `/health` on :80 | 5s | 10s |
| postgres | Exec | `pg_isready -U postgres` | 10s | 5s |
| redis | Exec | `redis-cli ping` | 5s | 5s |
| rabbitmq | Exec | `rabbitmq-diagnostics ping` | 20s | 30s |

---

## Persistent Volumes

| PVC | Storage | Used By |
|-----|---------|---------|
| postgres-pvc | 1Gi | postgres Deployment |
| redis-pvc | 512Mi | redis Deployment |

Both use `ReadWriteOnce` access mode (single node).

---

## Monitoring Stack

```mermaid
flowchart TB
    subgraph Prometheus["📊 Prometheus"]
        P1["RBAC: ServiceAccount + ClusterRole"]
        P2["ScrapeConfig: 8 targets"]
        P3["NodePort: 9090"]
    end

    subgraph Grafana["📈 Grafana"]
        G1["Auto-provisioned datasources\n(Prometheus + Loki)"]
        G2["Pre-configured dashboard\n(15 panels)"]
        G3["NodePort: 30300"]
    end

    subgraph Loki["📝 Loki + Promtail"]
        L1["Loki: Log storage & query"]
        L2["Promtail: DaemonSet (every node)"]
    end

    Prometheus & Grafana & Loki

    style Prometheus fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
    style Grafana fill:#16213e,stroke:#e94560,color:#e94560
    style Loki fill:#0f3460,stroke:#00d9ff,color:#00d9ff
```

---

## Startup Behavior

Services may CrashLoop on first start because they begin before Postgres/Redis are fully ready. This is expected — the services self-heal after 3-5 restarts as dependencies become available. No manual intervention required.

---

## Useful Commands

```mermaid
flowchart TB
    subgraph Commands["🔧 kubectl Commands"]
        C1["kubectl get pods -o wide"]
        C2["kubectl logs -f deployment/user-service"]
        C3["kubectl describe deployment registration-service"]
        C4["kubectl port-forward svc/nginx 8081:80 --address 0.0.0.0"]
        C5["kubectl port-forward svc/prometheus 9090:9090 --address 0.0.0.0"]
        C6["kubectl scale deployment user-service --replicas=3"]
        C7["kubectl rollout restart deployment user-service"]
        C8["./manage.sh k8s-down"]
    end

    style Commands fill:#1a1a2e,stroke:#00d9ff,color:#00d9ff
```

```bash
# Check pod status
kubectl get pods -o wide

# View pod logs
kubectl logs -f deployment/user-service

# Describe a deployment
kubectl describe deployment registration-service

# Port-forward for local access (Windows/Docker Desktop)
kubectl port-forward svc/nginx 8081:80 --address 0.0.0.0
# Then open http://localhost:8081

# Port-forward monitoring
kubectl port-forward svc/prometheus 9090:9090 --address 0.0.0.0
kubectl port-forward svc/grafana 3000:3000 --address 0.0.0.0

# Scale a service
kubectl scale deployment user-service --replicas=3

# Restart a deployment
kubectl rollout restart deployment user-service

# Delete everything
./manage.sh k8s-down
```