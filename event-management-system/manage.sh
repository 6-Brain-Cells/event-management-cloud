#!/bin/bash
# ─────────────────────────────────────────────────────────────────
# Event Management System — Environment Manager
# Usage: ./manage.sh [command] [environment]
# ─────────────────────────────────────────────────────────────────

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
  echo "    ./manage.sh up dev --monitor     # + Prometheus/Grafana"
  echo "    ./manage.sh up test              # Start test (http://localhost:8081)"
  echo "    ./manage.sh up prod              # Start prod (http://localhost:8082)"
  echo "    ./manage.sh up dev & ./manage.sh up prod  # Both simultaneously"
  echo ""
}

get_compose_files() {
  local env="$1"
  local monitor="$2"
  local files="$BASE -f docker-compose.${env}.yml"
  [ "$monitor" = "--monitor" ] && files="$files $MONITORING"
  echo "$files"
}

case "$1" in
  up)
    ENV="${2:-dev}"
    FILES=$(get_compose_files "$ENV" "${3:-}")
    echo "▶  Starting $ENV environment..."
    
    # shellcheck disable=SC2086
    if [ "$ENV" = "prod" ]; then
      $COMPOSE -p "event-$ENV" $FILES up --build -d --scale user-service=2 --scale event-service=2
    else
      $COMPOSE -p "event-$ENV" $FILES up --build -d
    fi
    
    echo ""
    echo "✅  $ENV environment running:"
    case "$ENV" in
      dev)  echo "   Frontend:    http://localhost:8080" ;;
      test) echo "   Frontend:    http://localhost:8081" ;;
      prod) echo "   Frontend:    http://localhost:8082" ;;
    esac
    [ "${3:-}" = "--monitor" ] && echo "   Prometheus:  http://localhost:9090" && echo "   Grafana:     http://localhost:3000 (admin/admin)"
    ;;

  down)
    ENV="${2:-dev}"
    FILES=$(get_compose_files "$ENV" "${3:-}")
    echo "⏹  Stopping $ENV environment..."
    # shellcheck disable=SC2086
    $COMPOSE -p "event-$ENV" $FILES down
    ;;

  build)
    ENV="${2:-dev}"
    FILES=$(get_compose_files "$ENV" "${3:-}")
    echo "🔨  Building $ENV images..."
    # shellcheck disable=SC2086
    $COMPOSE -p "event-$ENV" $FILES build
    ;;

  logs)
    ENV="${2:-dev}"
    FILES=$(get_compose_files "$ENV" "${3:-}")
    # shellcheck disable=SC2086
    $COMPOSE -p "event-$ENV" $FILES logs -f
    ;;

  test)
    echo "🧪  Running integration tests..."
    # shellcheck disable=SC2086
    $COMPOSE -p "event-test" $BASE -f docker-compose.test.yml up --build --abort-on-container-exit --exit-code-from test-runner
    ;;

  k8s-up)
    echo "☸️  Deploying to Minikube..."
    # Build images inside Minikube's Docker daemon
    eval "$(minikube docker-env)"
    docker build -t event-mgmt/user-service:latest ./services/user-service
    docker build -t event-mgmt/event-service:latest ./services/event-service
    docker build -t event-mgmt/registration-service:latest ./services/registration-service
    docker build -t event-mgmt/notification-service:latest ./services/notification-service
    docker build -t event-mgmt/nginx:latest ./nginx
    # Apply manifests
    kubectl apply -f k8s/configmaps/
    kubectl apply -f k8s/deployments/
    kubectl apply -f k8s/services/
    echo ""
    echo "✅  Deployed to Minikube"
    echo "   Run: minikube service nginx --url"
    ;;

  k8s-down)
    echo "☸️  Removing from Minikube..."
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
    # shellcheck disable=SC2086
    $COMPOSE -p "event-dev" $BASE -f docker-compose.dev.yml down -v --remove-orphans 2>/dev/null || true
    # shellcheck disable=SC2086
    $COMPOSE -p "event-test" $BASE -f docker-compose.test.yml down -v --remove-orphans 2>/dev/null || true
    # shellcheck disable=SC2086
    $COMPOSE -p "event-prod" $BASE -f docker-compose.prod.yml down -v --remove-orphans 2>/dev/null || true
    echo "✅  Cleaned"
    ;;

  *)
    show_help
    ;;
esac