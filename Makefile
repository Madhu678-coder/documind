.PHONY: help setup up down restart logs build clean reset shell-backend shell-db

help:
	@echo "DocuMind Development Commands"
	@echo ""
	@echo "  make setup        - Complete setup (AWS, S3, Docker)"
	@echo "  make up           - Start all services"
	@echo "  make down         - Stop all services"
	@echo "  make restart      - Restart all services"
	@echo "  make logs         - View logs (all services)"
	@echo "  make build        - Rebuild all services"
	@echo "  make clean        - Stop and remove containers"
	@echo "  make reset        - Complete reset (removes volumes)"
	@echo "  make shell-backend - Open backend shell"
	@echo "  make shell-db     - Open PostgreSQL shell"
	@echo ""

setup:
	./setup.sh

up:
	docker-compose up -d

down:
	docker-compose down

restart:
	docker-compose restart

logs:
	docker-compose logs -f

build:
	docker-compose up -d --build

clean:
	docker-compose down --remove-orphans

reset:
	docker-compose down -v
	docker-compose up -d --build

shell-backend:
	docker-compose exec backend bash

shell-db:
	docker-compose exec postgres psql -U documind -d documind
