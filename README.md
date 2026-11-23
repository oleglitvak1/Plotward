# Plotward

A backend that builds a memory of your garden from photos. See
[docs/architecture.md](docs/architecture.md) for the design.

## Status: milestone 1 (skeleton)

- Postgres 16 with PostGIS and pgvector, schema managed by Alembic (`infra/migrations`).
- `POST /photos` ingests JPEG and HEIC: content-hash dedupe, raw EXIF kept as JSON, GPS and
  capture time parsed, an orientation-corrected master and thumbnail written, and an
  `embed_photo` job queued for milestone 2.
- Every garden-scoped query is filtered by `garden_id` in one place (`plotward_core/scoping.py`).

## Run it

```bash
cp .env.example .env        # set PLOTWARD_API_KEY
make up                     # Postgres + API on http://127.0.0.1:8000
```

```bash
curl -H "X-API-Key: $PLOTWARD_API_KEY" -F file=@IMG_0001.jpg http://127.0.0.1:8000/photos
```

A first upload returns `201`; the same bytes again return `200` with `"duplicate": true`.

Photos are stored in `~/plotward-data` by default, outside the repo (change it with
`PLOTWARD_DATA_HOST_DIR` in `.env`). The database lives in the `pgdata` Docker volume. Back up both.

## Develop

```bash
make install   # uv workspace
make test      # needs Postgres with PostGIS and pgvector, see below
make lint
```

Tests build a fresh schema with the real migrations in a database named `plotward_test`
(override with `PLOTWARD_TEST_DATABASE_URL`). Start just the database with
`docker compose -f infra/docker-compose.yml up -d db` and create the test database:
`createdb -h localhost -U plotward plotward_test`.

## Layout

```
apps/api         FastAPI service
packages/core    models, scoping, ingest, config
infra            docker-compose, Dockerfiles, migrations
docs             architecture and decision records
```
