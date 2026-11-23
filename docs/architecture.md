# Plotward: PoC and Architecture

Nov 22, 2026 · Oleg

> Exported from the living design doc. The architecture diagram is not included here; see the doc for the picture (6 components, 3 outside services).

## Vision and goals

Plotward is a backend that builds a memory of your garden from photos, asks you questions to fill the gaps, and gradually turns that memory into reminders, warnings and tips. You are the first and only user; the design should not block other users later.

- **Real backend, real ML/AI practice:** photo ingestion, vector retrieval, a tool-calling LLM agent, an eval harness and cost tracking.
- **Low cost:** no model training and no GPU. Use the cheapest Claude model that passes your own eval cases; run image embeddings locally.
- **Earns trust in stages:** observe, ask, remind, warn, advise. The system claims no expertise about a zone until it has the history to back it.
- **Multi-user ready, not multi-user built:** `garden_id` on every table, per-garden data that can be exported or deleted, no billing or sharing yet.

## PoC scope

The PoC proves one loop end to end: a photo comes in, the system recognizes or creates the plant, asks you what it is unsure about, and answers your questions from your own records.

**In scope**

- Photos from your Pixel, shot in a camera app that saves to a dedicated folder (Open Camera or similar) and synced to the server with EXIF (time, GPS) intact.
- Cold start: no manual plant registration. A photo with no confident match becomes a new plant after you confirm one question.
- Image embeddings on your Mac, stored in Postgres with pgvector.
- A daily-capped question loop (one-tap answers) that turns your answers into verified labels.
- Ask the garden: a chat endpoint where Claude calls tools (find plant, similar photos, care log, weather) instead of guessing.
- A frost alert from the National Weather Service API as the first proactive feature.
- A `model_call` log with cost per call, a monthly budget cap, and a small eval set built from your verdicts.
- Care logging through the chat (a `log_care` tool), so "when did I last prune X?" has data to answer from.

**Deferred**

- Overhead map and zone polygons, fixed cameras, storage retention tiers.
- Local vision-language models, a learned router, small trained classifiers.
- A native app, multi-user features, Kubernetes.

## Architecture

The PoC is a handful of containers on your Mac plus three outside services.

Photos arrive in a watched folder, the worker embeds them and writes to Postgres, and the API reads the same database to answer your questions through Claude. Only the worker and API reach outside services, and every Claude call goes through one logging wrapper.

**Tech picks**

- Python 3.12 with FastAPI, a uv workspace, and Alembic migrations.
- Postgres with pgvector and PostGIS; a Postgres-backed job queue to start.
- open_clip or SigLIP for image embeddings behind a small interface.
- Anthropic Python SDK for vision, tool calling, prompt caching and batch.
- Docker Compose for local services, Syncthing for capture, ntfy for push.

## Data model

Eight tables carry the PoC (the job queue and saved eval cases add two more), all in one Postgres database with the pgvector and PostGIS extensions.

| Table | Purpose | Key fields |
| --- | --- | --- |
| `garden` | Tenant boundary | id, name, timezone, home location |
| `zone` | Optional named area (bed, orchard) | garden_id, name, polygon (PostGIS) |
| `plant` | One physical plant | garden_id, zone_id, species, cultivar, planted_date, location (PostGIS point), status |
| `photo` | One uploaded image | garden_id, plant_id (nullable), captured_at, received_at, raw EXIF, GPS point, file key, content hash, embedding (pgvector), embedding model and version, storage_tier |
| `label` | Verified fact about a plant or photo | target, field, value, source (user or model), confirmed_at |
| `care_event` | Something you did | plant_id, type (water, prune, fertilize), date, note |
| `question` | A prompt the system asked you | target, prompt, options, status, asked_at, answered_at |
| `model_call` | Every LLM call | feature, model, tokens in and out, cost, latency, model_tier, confidence |

Rules that keep it multi-user ready and cheap to change:

- Every table has `garden_id` and every query goes through one repository layer that filters on it, with a test that fails if a query skips the filter. Row-level security waits for a second user.
- Photos are identified by content hash, never by file path. Store `captured_at` (from EXIF) and `received_at` (server clock) separately.
- Keep raw EXIF as JSON next to the parsed fields, so matching can be redone later.
- Labels are append-only with a source, so a user-confirmed value always outranks a model guess. Current values come from a view that takes the latest user label, else the latest model label.
- Eval cases are saved from your verdicts on answers: input references, expected answer, and a pass or fail result per run.

## Key flows

Four flows cover everything the PoC does. Only flows 2 and 3 spend model money.

**1. Photo ingest and plant matching**

1. Syncthing delivers a new file from your Pixel to a watched folder; the worker picks it up.
2. Parse EXIF (capture time, GPS, heading), hash the file, create a resized master and a thumbnail.
3. Embed the image locally and store the vector.
4. Search existing plants by GPS proximity first, then by embedding similarity.
5. Confident match: attach the photo to that plant. No match: create a draft plant and queue a question. Photos taken within a minute and a few meters of each other are grouped first, so one pass along a bed does not create many drafts.

**2. Question loop**

1. Pick the highest-value open question (new plant, uncertain species, unexplained change) within the daily cap.
2. Claude drafts a one-tap question with a suggested answer; a push notification (ntfy) delivers it.
3. Your answer becomes a verified label. A skip is recorded and respected.

**3. Ask the garden**

1. You send a question, optionally with a photo.
2. Claude calls tools: find plant, search similar photos, read care log, log care, get weather.
3. The answer cites the records it used, and the call is logged with tokens and cost.
4. You mark the answer right or wrong, which saves it as an eval case.

**4. Proactive alerts**

1. A scheduler checks the NWS forecast for your location.
2. Frost or heat thresholds are matched against the plants you have labeled as sensitive.
3. Batch into one notification per day at most. This flow is rules only, with no model call.

## AI and cost strategy

The PoC uses Claude models only, starting with the cheapest one that passes your eval cases, and keeps seams so cheaper tiers can be added once there is data to justify them.

- **Model per task, in config:** Haiku-class by default for question drafting, summaries and first-pass diagnosis. A larger model is used only for cases the eval set shows Haiku gets wrong. Check Anthropic's pricing page when setting budgets.
- **Embeddings stay local:** Claude has no embeddings API, so open_clip or SigLIP runs in the worker container on CPU, which is plenty for tens of photos a day, and feeds pgvector. A native Metal service can replace it later behind the same interface.
- **One wrapper for every call:** `llm.py` handles model choice, retries, logging and the budget cap. Every call writes a `model_call` row with feature, model, tokens, cost, latency and a confidence value.
- **Send less:** downscale and crop images, send two or three photos instead of the full history, and keep a rolling per-plant summary.
- **Cache and batch:** prompt caching for stable per-plant context, a cache keyed by photo hash and prompt version, and the batch API for the nightly digest.
- **Budget governor:** a monthly cap per feature. Past the cap, the feature falls back to rules and templates instead of failing.

**Later cascade, once labels and evals exist:** rules, embedding nearest neighbors, a small classifier trained on your labels, a local vision-language model, then a larger Claude model, with a small router picking the tier from cheap signals such as the lower tier's confidence and distance from the zone baseline. At a few calls a day the API costs pennies, so moving tiers local is about learning, privacy and independence, not savings.

## Hardware and capture

The PoC needs no new hardware: your MacBook Air (M4, 24 GB) runs the backend and your Pixel captures photos.

| Piece | PoC choice | Later |
| --- | --- | --- |
| Server | MacBook Air M4, 24 GB, Docker Desktop | Always-on mini PC or spare computer |
| Capture | Pixel, JPEG with GPS on, saved to a dedicated folder, synced by Syncthing | Weatherproof fixed cameras (PoE or Wi-Fi) |
| Embeddings | open_clip or SigLIP on CPU in the worker container | Native Metal service behind the same interface |
| Photo storage | Local disk | Object storage (MinIO, R2) plus retention tiers |
| Access | Same network | Tailscale for remote access |

Notes:

- Docker on macOS cannot use the Apple GPU, so any local model server runs natively on macOS and containers call it through `host.docker.internal`.
- The Air is fanless and sleeps, so it suits catch-up batch work, not continuous load. The ingest worker simply processes the backlog when it wakes. Alerts are best effort in the PoC: the frost check runs only while the Mac is awake, so a closed-lid night can miss one.
- The old iPhone is not weatherproof and iOS limits background camera use, so it serves as a test device, not an outdoor camera.
- Storage grows mainly from routine photos. Keep embeddings, thumbnails, metadata and labeled photos forever; downsample or expire routine frames later. A rough planning figure is tens of GB per fixed camera per year, to be measured.
- Back up the database and photos: a nightly `pg_dump` plus a copy of the photo folder to an external drive or cloud bucket. The garden's memory is the product, and the Mac is a laptop.

## Repo structure

A single monorepo holding client and server is the right choice for one developer: one clone, one set of tooling, and a change that spans the API and a client lands in one commit. Split only if you later need separate release cycles, separate access control, or to open-source one part.

```text
plotward/
  apps/
    api/          FastAPI service (HTTP, auth, query agent)
    worker/       ingest, embedding, question scheduler, alerts
  packages/
    core/         domain models, DB access, llm.py wrapper, budget cap
    ml/           embedding interface and implementations
  clients/        empty in the PoC; web or mobile apps land here later
  evals/          saved cases and the runner
  infra/          docker-compose, Postgres init, migrations
  docs/           architecture notes and decision records
```

Rules that keep a monorepo healthy:

- **One direction of dependency:** apps import from `packages`, never from each other. Clients talk to the API only over HTTP.
- **The API is the contract:** generate an OpenAPI spec from FastAPI and produce client types from it, so a future Kotlin or TypeScript client cannot drift from the server.
- **The ML boundary stays thin:** `packages/ml` exposes image bytes in, vector out. The model behind it can change without touching callers.
- **Tooling:** a Python workspace managed by uv, Alembic for migrations, ruff and pytest, and a Makefile or justfile for the common commands.

## Milestones and success criteria

Six milestones, each a few evenings of work. Each one ends with something you can run.

1. **Skeleton:** Docker Compose, Postgres with pgvector, the schema, and an upload and ingest endpoint that handles HEIC and JPEG and stores raw EXIF.
2. **Embed and match:** local embeddings, similarity search, and the cold-start flow that creates a draft plant from an unmatched photo.
3. **Capture path:** Syncthing from the Pixel's dedicated camera folder into the watched folder, so walking the yard feeds the system with no manual upload.
4. **Ask the garden:** the chat endpoint with Claude tool calling, including care logging, plus the `llm.py` wrapper that logs every call.
5. **Question loop:** daily-capped questions, ntfy delivery, and answers stored as verified labels.
6. **Evals and guardrails:** saved cases from your verdicts, a rerun script, the monthly budget cap, and the NWS frost alert.

**The PoC succeeds if, after about two weeks of real use:**

- A new photo of a known plant attaches to the right plant at least 80% of the time, and you can see how often it does not.
- "What is this plant?" and "When did I last prune X?" return correct answers from your own records.
- You answer most daily questions in one tap and have not muted the notifications.
- Total model spend is known per feature and stays under the monthly cap.
- The eval set has enough cases to compare Haiku against a larger model.

**Open questions**

- Is Haiku accurate enough for first-pass diagnosis, or does it need a larger model on hard cases?
- Which plant-ID service to use as the species suggestion fallback, and its free-tier limits.
- Whether Syncthing on the Pixel is reliable enough in the background, or a small upload app is needed.
- Where the repo lives: built here and copied to the Mac, or written directly into a folder on the Mac.
- Matching thresholds: what GPS radius and similarity score count as a confident match, to be tuned on your first hundred photos.
- Where frost sensitivity comes from: a hand-kept species table, or a Claude lookup cached per species.
