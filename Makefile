# RootAgent Makefile
# Usage: make [target]

.PHONY: help build up down restart logs logs-backend logs-frontend logs-redis shell-backend shell-frontend clean prune dev dev-backend dev-frontend dev-redis

# Default target
help:
	@echo "RootAgent Commands:"
	@echo ""
	@echo "=== Docker Commands ==="
	@echo "  make build        - Build all Docker images"
	@echo "  make up           - Start all services (detached)"
	@echo "  make up-build     - Build and start all services"
	@echo "  make down         - Stop all services"
	@echo "  make restart      - Restart all services"
	@echo "  make logs         - View all logs (follow)"
	@echo "  make logs-backend - View backend logs"
	@echo "  make ps           - Show running containers"
	@echo "  make clean        - Stop and remove containers"
	@echo ""
	@echo "=== Local Development ==="
	@echo "  make dev          - Run backend + Redis locally (no Docker for backend)"
	@echo "  make dev-backend  - Run backend only (assumes Redis running)"
	@echo "  make dev-frontend - Serve frontend with Python HTTP server"
	@echo "  make dev-redis    - Start Redis in Docker only"
	@echo "  make dev-stop     - Stop all local dev services"
	@echo "  make install      - Install Python dependencies to venv"
	@echo "  make test         - Run tests"
	@echo ""
	@echo "First time setup:"
	@echo "  cp .env.example .env"
	@echo "  make install"
	@echo "  make dev"

# ================================
# Docker Commands
# ================================

# Build all images
build:
	docker compose build

# Build without cache
build-fresh:
	docker compose build --no-cache

# Start services
up:
	docker compose up -d

# Start with build
up-build:
	docker compose up -d --build

# Stop services
down:
	docker compose down

# Stop and remove volumes (WARNING: deletes Redis data)
down-volumes:
	docker compose down -v

# Restart all services
restart:
	docker compose restart

# Restart specific service
restart-backend:
	docker compose restart backend

restart-frontend:
	docker compose restart frontend

# View all logs
logs:
	docker compose logs -f

# View specific service logs
logs-backend:
	docker compose logs -f backend

logs-frontend:
	docker compose logs -f frontend

logs-redis:
	docker compose logs -f redis

# Show running containers
ps:
	docker compose ps

# Open shell in containers
shell-backend:
	docker compose exec backend /bin/bash

shell-frontend:
	docker compose exec frontend /bin/sh

shell-redis:
	docker compose exec redis redis-cli

# Health check
health:
	@curl -s http://localhost/health || echo "Service not responding"

# Clean up
clean: down
	docker compose rm -f

# Remove all unused Docker resources (careful!)
prune:
	docker system prune -f

# Full reset (WARNING: removes everything including volumes)
reset: down-volumes
	docker compose rm -f
	docker system prune -f

# ================================
# Local Development Commands
# ================================

# Install dependencies
install:
	@if [ ! -d ".venv" ]; then python3 -m venv .venv; fi
	@. .venv/bin/activate && pip install -e . 2>/dev/null || pip install -r requirements.txt 2>/dev/null || uv sync

# Run Redis in Docker only (for local dev)
dev-redis:
	docker compose up -d redis

# Run backend locally (assumes Redis is running)
dev-backend:
	@echo "Starting backend locally..."
	@. .venv/bin/activate && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

# Run backend + Redis (Redis in Docker, backend local)
dev: dev-redis
	@echo "Redis started in Docker. Starting backend locally..."
	@sleep 2
	@. .venv/bin/activate && uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload

# Serve frontend locally with Python HTTP server
dev-frontend:
	@echo "Serving frontend at http://localhost:3000"
	@cd frontend && python3 -m http.server 3000

# Stop Redis (Docker) used for local dev
dev-stop-redis:
	docker compose stop redis
	docker compose rm -f redis

# Stop all local dev processes (kills uvicorn and http.server)
dev-stop:
	@echo "Stopping local development services..."
	@-pkill -f "uvicorn backend.app.main:app" 2>/dev/null || true
	@-pkill -f "python3 -m http.server" 2>/dev/null || true
	@docker compose stop redis 2>/dev/null || true
	@echo "Local dev services stopped."

# Run tests
test:
	@. .venv/bin/activate && pytest backend/tests/ -v

# Run tests with coverage
test-cov:
	@. .venv/bin/activate && pytest backend/tests/ -v --cov=backend
