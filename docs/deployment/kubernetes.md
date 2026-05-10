# Kubernetes Deployment

## Overview

The project includes Kubernetes manifests for deploying the full stack to a Minikube cluster. All images use `imagePullPolicy: Never` — they must be built inside Minikube's Docker daemon.

---

## Prerequisites

- Minikube (`minikube start`)
- kubectl
- Docker

---

## Quick Start

```bash
# Start Minikube
minikube start --memory=8192 --cpus=4

# Use Minikube's Docker daemon
eval $(minikube docker-env)

# Build all images
docker compose -f docker-compose.yml build

# Apply manifests in order
kubectl apply -f k8s/configmaps/
kubectl apply -f k8s/services/
kubectl apply -f k8s/deployments/
kubectl apply -f k8s/monitoring/

# Wait for pods
kubectl get pods -w

# Access the app
minikube service nginx-service
```

---

## Directory Structure

```
k8s/
├── configmaps/
│   └── config.yaml            # ConfigMap + Secret
├── deployments/
│   └── deployments.yaml       # 11 Deployments + 1 DaemonSet + 2 PVCs
├── services/
│   └── services.yaml          # 12 Services
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
| **Deployments** | 11 | 4 services + postgres + redis + rabbitmq + nginx + prometheus + grafana + loki |
| **DaemonSets** | 1 | promtail (log collection on every node) |
| **Services** | 12 | ClusterIP (internal) + NodePort (external) |
| **ConfigMaps** | 1 | Application configuration (DB host, ports) |
| **Secrets** | 1 | DB password, Redis password, RabbitMQ credentials |
| **PVCs** | 2 | postgres (1Gi), redis (512Mi) |
| **ServiceAccounts** | 1 | prometheus |
| **ClusterRoles** | 1 | prometheus (kube-api read access) |
| **ClusterRoleBindings** | 1 | prometheus ↔ ServiceAccount |

---

## Configuration

### ConfigMap (`k8s/configmaps/config.yaml`)

Contains non-sensitive configuration:
- DB host, port, name, user
- Redis host, port
- RabbitMQ host, port, user
- Service URLs

### Secret (`k8s/configmaps/config.yaml`)

Contains sensitive credentials:
- `DB_PASSWORD`
- `REDIS_PASSWORD`
- `RABBITMQ_PASSWORD`

All app service Deployments reference the Secret via `secretKeyRef`:

```yaml
env:
  - name: DB_PASSWORD
    valueFrom:
      secretKeyRef:
        name: event-management-secret
        key: DB_PASSWORD
```

---

## Services

| Service | Type | Port | Target |
|---------|------|------|--------|
| postgres-service | ClusterIP | 5432 | postgres:5432 |
| redis-service | ClusterIP | 6379 | redis:6379 |
| rabbitmq-service | ClusterIP | 5672 | rabbitmq:5672 |
| rabbitmq-management-service | ClusterIP | 15672 | rabbitmq:15672 |
| user-service | ClusterIP | 8000 | user-service:8000 |
| event-service | ClusterIP | 8000 | event-service:8000 |
| registration-service | ClusterIP | 8000 | registration-service:8000 |
| notification-service | ClusterIP | 8000 | notification-service:8000 |
| nginx-service | NodePort | 80 | nginx:80 |
| prometheus-service | NodePort | 9090 | prometheus:9090 |
| grafana-service | NodePort | 30300 | grafana:3000 |
| loki-service | ClusterIP | 3100 | loki:3100 |

---

## Persistent Volumes

| PVC | Storage | Used By |
|-----|---------|---------|
| postgres-pvc | 1Gi | postgres Deployment |
| redis-pvc | 512Mi | redis Deployment |

---

## Monitoring Stack

### Prometheus

- **RBAC:** ServiceAccount + ClusterRole + ClusterRoleBinding for Kubernetes API discovery
- **ConfigMap:** Scrape configuration embedded in ConfigMap
- **Targets:** 4 app services via Kubernetes service discovery
- **NodePort:** 9090

### Grafana

- **Datasources:** Auto-provisioned via ConfigMap (Prometheus + Loki)
- **Dashboard:** Pre-configured with the event management overview dashboard
- **Credentials:** Admin password from Secret via `secretKeyRef`
- **NodePort:** 30300

### Loki + Promtail

- **Loki:** Log storage and query engine
- **Promtail:** DaemonSet that collects logs from every node and ships to Loki

---

## Useful Commands

```bash
# Check pod status
kubectl get pods -o wide

# View pod logs
kubectl logs -f deployment/user-service

# Describe a deployment
kubectl describe deployment registration-service

# Port-forward for local access
kubectl port-forward svc/nginx-service 8080:80

# Scale a service
kubectl scale deployment user-service --replicas=3

# Restart a deployment
kubectl rollout restart deployment user-service

# Delete everything
kubectl delete -f k8s/monitoring/
kubectl delete -f k8s/deployments/
kubectl delete -f k8s/services/
kubectl delete -f k8s/configmaps/
```
