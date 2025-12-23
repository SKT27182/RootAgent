# =============================================================================
# RootAgent Makefile
# Usage:
#   make up-build          # runs v1 (default)
#   make up-build v=v2     # runs v2
#   make up v=v1           # rollback to v1
# =============================================================================

.PHONY: help build build-fresh up up-build up-build-debug down down-volumes \
        restart restart-backend restart-frontend logs logs-backend logs-frontend \
        logs-redis ps shell-backend shell-frontend shell-redis clean prune reset \
        dev dev-backend dev-frontend dev-redis dev-stop dev-stop-redis \
        install test test-cov health

# ================================
# Version handling
# ================================
APP_NAME ?= rootagent
v ?= v1

export APP_NAME
export APP_VERSION := $(v)

# ================================
# Help
# ================================
help:
	@echo "RootAgent Commands:"
	@echo ""
	@echo "=== Docker Commands ==="
	@echo "  make build              - Build images (default v1)"
	@echo "  make build v=v2         - Build images with version v2"
	@echo "  make up                 - Start services"
	@echo "  make up v=v2            - Start services with version v2"
	@echo "  make up-build           - Build + start services"
	@echo "  make up-build v=v2      - Build + start version v2"
	@echo "  make down               - Stop services"
	@echo "  make restart            - Restart services"
	@echo "  make logs               - Follow all logs"
	@echo "  make ps                 - Show running containers"
	@echo "  make clean              - Stop and remove containers"
	@echo ""
	@echo "=== Local Development ==="
	@echo "  make dev                - Backend + Redis (backend local)"
	@echo "  make dev-backend        - Backend only"
	@echo "  make dev-frontend       - Frontend locally"
	@echo "  make dev-redis          - Redis in Docker"
	@echo "  make dev-stop           - Stop local dev services"
	@echo "  make install            - Install Python deps"
	@echo "  make test               - Run tests"
	@echo ""
	@echo "Current version: $(APP_VERSION)"

# ================================
# Docker Commands
# ================================

build:
	@echo "Building $(APP_NAME) version $(APP_VERSION)"
	docker compose build

build-fresh:
	@echo "Building $(APP_NAME) version $(APP_VERSION) (no cache)"
	docker compose build --no-cache

up:
	@echo "Starting $(APP_NAME) version $(APP_VERSION)"
	docker compose up -d

up-build:
	@echo "Building & starting $(APP_NAME) version $(APP_VERSION)"
	docker compose up -d --build

up-build-debug:
	@echo "Building & starting $(APP_NAME) version $(APP_VERSION) (foreground)"
	docker compose up --build

down:
	docker compose down

down-volumes:
	docker compose down -v

restart:
	docker compose restart

restart-backend:
	docker compose restart backend

restart-frontend:
	docker compose restart frontend

logs:
	docker compose logs -f

logs-backend:
	docker compose logs -f backend

logs-frontend:
	docker compose logs -f frontend

logs-redis:
	docker compose logs -f redis

ps:
	docker compose ps

shell-backend:
	docker compose exec backend /bin/bash

shell-frontend:
	docker compose exec frontend /bin/sh

shell-redis:
	docker compose exec redis redis-cli

health:
	@curl -s http://localhost/health || echo "Service not responding"

clean: down
	docker compose rm -f

prune:
	docker system prune -f

reset: down-volumes
	docker compose rm -f
	docker system prune -f

# ================================
# Local Development
# ================================

install:
	@if [ ! -d ".venv" ]; then python3 -m venv .venv; fi
	@. .venv/bin/activate && pip install -e . 2>/dev/null || \
	  pip install -r requirements.txt 2>/dev/null || uv sync

dev-redis:
	docker compose up -d redis

dev-backend:
	@echo "Starting backend locally..."
	@. .venv/bin/activate && \
	 uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

dev: dev-redis
	@echo "Redis started. Starting backend locally..."
	@sleep 2
	@. .venv/bin/activate && \
	 uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

dev-frontend:
	@echo "Serving frontend at http://localhost:3000"
	@cd frontend && python3 -m http.server 3000

dev-stop-redis:
	docker compose stop redis
	docker compose rm -f redis

dev-stop:
	@echo "Stopping local dev services..."
	@-pkill -f "uvicorn backend.app.main:app" 2>/dev/null || true
	@-pkill -f "python3 -m http.server" 2>/dev/null || true
	@docker compose stop redis 2>/dev/null || true
	@echo "Local dev services stopped."

# ================================
# Tests
# ================================

test:
	@. .venv/bin/activate && pytest backend/tests/ -v

test-cov:
	@. .venv/bin/activate && pytest backend/tests/ -v --cov=backend
