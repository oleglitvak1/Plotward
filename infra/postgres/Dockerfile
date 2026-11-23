# Postgres 16 with PostGIS and pgvector, both from the PostgreSQL apt repository
# (already configured in the official image). Works on Intel and Apple Silicon.
FROM postgres:16-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-16-postgis-3 \
        postgresql-16-pgvector \
    && rm -rf /var/lib/apt/lists/*
