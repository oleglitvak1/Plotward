.PHONY: install up down migrate dev worker report test lint fmt

COMPOSE = docker compose -f infra/docker-compose.yml --env-file .env

install:
	uv sync --all-packages

up:
	$(COMPOSE) up --build -d

down:
	$(COMPOSE) down

migrate:
	uv run --all-packages alembic -c infra/alembic.ini upgrade head

dev:
	uv run --all-packages uvicorn plotward_api.main:app_factory --factory --reload

worker:
	uv run --all-packages python -m plotward_worker

report:
	uv run --all-packages python -m plotward_worker.report

test:
	uv run --all-packages pytest

lint:
	uv run --all-packages ruff check .
	uv run --all-packages ruff format --check .

fmt:
	uv run --all-packages ruff check . --fix
	uv run --all-packages ruff format .
