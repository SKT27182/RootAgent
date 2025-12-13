# RootAgent Docker Makefile
# Usage: make [target]

.PHONY: help build up down restart logs logs-backend logs-frontend logs-redis shell-backend shell-frontend clean prune

# Default target
help:
	@echo "RootAgent Docker Commands:"
	@echo ""
	@echo "  make build        - Build all images"
	@echo "  make up           - Start all services (detached)"
	@echo "  make down         - Stop all services"
	@echo "  make restart      - Restart all services"
	@echo "  make logs         - View all logs (follow)"
	@echo "  make logs-backend - View backend logs"
	@echo "  make logs-frontend- View frontend logs"
	@echo "  make logs-redis   - View redis logs"
	@echo "  make shell-backend- Open shell in backend container"
	@echo "  make shell-frontend- Open shell in frontend container"
	@echo "  make ps           - Show running containers"
	@echo "  make clean        - Stop and remove containers"
	@echo "  make prune        - Remove all unused Docker resources"
	@echo ""
	@echo "First time setup:"
	@echo "  cp .env.example .env"
	@echo "  # Edit .env with your API keys"
	@echo "  make build"
	@echo "  make up"

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
