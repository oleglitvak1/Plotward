FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PATH="/app/.venv/bin:$PATH"

COPY pyproject.toml uv.lock ./
COPY packages ./packages
COPY apps ./apps
COPY infra/alembic.ini ./infra/alembic.ini
COPY infra/migrations ./infra/migrations
RUN uv sync --frozen --no-dev --package plotward-api

EXPOSE 8000
CMD ["sh", "-c", "alembic -c infra/alembic.ini upgrade head && exec uvicorn plotward_api.main:app_factory --factory --host 0.0.0.0 --port 8000"]
