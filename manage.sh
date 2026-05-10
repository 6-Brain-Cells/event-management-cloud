#!/bin/bash
set -e

COMPOSE="docker compose"
BASE="-f docker-compose.yml"
MONITORING="-f docker-compose.monitoring.yml"

show_help() {
  echo ""
  echo "  EventHub Management Script"
  echo ""
  echo "  Usage: ./manage.sh <command> [env] [--monitor]"
  echo ""
  echo "  Commands:"
  echo "    up      dev|test|prod   Start environment"
  echo "    down    dev|test|prod   Stop environment"
  echo "    down-all                Stop all environments"
  echo "    logs    dev|test|prod   Tail logs"
  echo "    build   dev|test|prod   Rebuild images"
  echo "    test                    Run integration tests"
  echo "    k8s-up                  Deploy to Minikube"
  echo "    k8s-down                Remove from Minikube"
  echo "    status                  Show running containers"
  echo "    clean                   Remove all volumes and images"
  echo ""
  echo "  Examples:"
  echo "    ./manage.sh up dev               # Start dev (http://localhost:8080)"
  echo "    ./manage.sh up dev --monitor     # + Prometheus, Grafana, Loki, Promtail"
  echo "    ./manage.sh up test              # Start test (http://localhost:8081)"
  echo "    ./manage.sh up prod              # Start prod (http://localhost:8082)"
  echo "    ./manage.sh down-all             # Stop everything"
  echo ""
}

get_project() {
  echo "event-$1"
}

get_compose_files() {
  local env=$1
  local monitor=$2
  local files="$BASE -f docker-compose.${env}.yml"
  [ "$monitor" = "--monitor" ] && files="$files $MONITORING"
  echo "$files"
}

case "$1" in
  up)
    ENV=${2:-dev}
    PROJ=$(get_project $ENV)
    FILES=$(get_compose_files $ENV $3)
    echo "▶  Starting $ENV environment (project: $PROJ)..."
    $COMPOSE -p "$PROJ" $FILES up --build -d
    echo ""
    echo "✅  $ENV environment running:"
    case $ENV in
      dev)  echo "   Frontend:    http://localhost:8080" ;;
      test) echo "   Frontend:    http://localhost:8081" ;;
      prod) echo "   Frontend:    http://localhost:8082" ;;
    esac
    if [ "$3" = "--monitor" ]; then
      echo "   Prometheus:  http://localhost:9090"
      echo "   Loki:        http://localhost:3100"
      echo "   Promtail:    http://localhost:9080   (shipper health)"
      echo "   Grafana:     http://localhost:3000   (admin / admin)"
      echo ""
      echo "   ┌─ Grafana Quick Start ────────────────────────────────┐"
      echo "   │ Both Prometheus and Loki are auto-provisioned.       │"
      echo "   │ Go to Explore → Loki → run: {service=\"user-service\"}│"
      echo "   └──────────────────────────────────────────────────────┘"
    fi
    ;;

  down)
    ENV=${2:-dev}
    PROJ=$(get_project $ENV)
    FILES=$(get_compose_files $ENV)
    echo "⏹  Stopping $ENV environment..."
    $COMPOSE -p "$PROJ" $FILES down --remove-orphans
    ;;

  down-all)
    echo "⏹  Stopping all environments..."
    for env in dev test prod; do
      PROJ=$(get_project $env)
      FILES=$(get_compose_files $env)
      $COMPOSE -p "$PROJ" $FILES down --remove-orphans 2>/dev/null || true
    done
    echo "✅  All environments stopped"
    ;;

  build)
    ENV=${2:-dev}
    PROJ=$(get_project $ENV)
    FILES=$(get_compose_files $ENV)
    echo "🔨  Building $ENV images..."
    $COMPOSE -p "$PROJ" $FILES build
    ;;

  logs)
    ENV=${2:-dev}
    PROJ=$(get_project $ENV)
    FILES=$(get_compose_files $ENV)
    $COMPOSE -p "$PROJ" $FILES logs -f
    ;;

  test)
    echo "🧪  Running integration tests..."
    $COMPOSE -p event-test $BASE -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from test-runner
    ;;

  k8s-up)
    echo "☸️  Deploying to Minikube..."
    eval $(minikube docker-env)
    docker build -t event-mgmt/user-service:latest ./services/user-service
    docker build -t event-mgmt/event-service:latest ./services/event-service
    docker build -t event-mgmt/registration-service:latest ./services/registration-service
    docker build -t event-mgmt/notification-service:latest ./services/notification-service
    docker build -t event-mgmt/nginx:latest ./nginx
    kubectl apply -f k8s/configmaps/
    kubectl apply -f k8s/deployments/
    kubectl apply -f k8s/services/
    kubectl apply -f k8s/monitoring/
    echo ""
    echo "✅  Deployed to Minikube"
    echo "   App:      minikube service nginx --url"
    echo "   Logs:     kubectl port-forward svc/loki 3100:3100"
    echo "   Grafana:  kubectl port-forward svc/grafana 3000:3000"
    ;;

  k8s-down)
    echo "☸️  Removing from Minikube..."
    kubectl delete -f k8s/monitoring/ --ignore-not-found
    kubectl delete -f k8s/services/ --ignore-not-found
    kubectl delete -f k8s/deployments/ --ignore-not-found
    kubectl delete -f k8s/configmaps/ --ignore-not-found
    echo "✅  Done"
    ;;

  status)
    echo "📊  Running containers:"
    docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
    ;;

  clean)
    echo "🧹  Cleaning up all volumes and containers..."
    for env in dev test prod; do
      PROJ=$(get_project $env)
      FILES=$(get_compose_files $env)
      $COMPOSE -p "$PROJ" $FILES down -v --remove-orphans 2>/dev/null || true
    done
    echo "✅  Cleaned"
    ;;

  *)
    show_help
    ;;
esac
