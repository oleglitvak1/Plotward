# Milestone 2: embed and match

A photo that arrives through `POST /photos` now ends up attached to a plant, or starts a new
draft plant and queues a question. A worker does this in the background.

## How it works

```
POST /photos -> photo row + embed_photo job
worker: claim job -> embed master.jpg -> store vector -> match_photo -> job done
```

`match_photo` (`packages/core/src/plotward_core/matching.py`), in order:

1. **GPS first.** Living plants within `match_radius_m` (15 m). Embedding similarity to each
   plant's latest 5 photos chooses among them. The best must clear `match_min_similarity_near`
   and beat the runner-up by `match_margin`. A lone plant in range with no photos yet is matched
   on GPS alone.
2. **Embedding only** (no GPS, or nothing nearby): all living plants, with a stricter bar,
   `match_min_similarity_far`.
3. **One pass along a bed.** If nothing matched but another photo was taken within 60 s and 5 m,
   join that photo's (living) plant.
4. **Otherwise** create a draft plant at the photo's location and queue the question
   "What plant is this?".

Ended plants (`status = removed`) are never candidates, so next year's tomato in the same spot is
a new plant. Every decision is recorded on the photo (`match_method`, `match_score`).

The worker claims jobs with `FOR UPDATE SKIP LOCKED`, retries failures with exponential backoff
(5 attempts), reclaims jobs stuck `running` for 10 minutes, and is safe to run twice on the same
job.

## Decisions to review

- **Conservative thresholds** (0.85 near, 0.93 far, margin 0.03). With the real model, even
  unrelated synthetic images scored 0.87 against each other, so a low bar matches almost
  anything. A wrong match silently corrupts a plant's history; a missed match costs one question.
  These are guesses until there are real photos. **Run `make report` after your first batch.**
- **Grouping only applies when nothing else matched**, and only to living plants. The doc says
  "grouped first"; applying it first would merge two different plants photographed seconds apart.
- **No GPS, no grouping.** Without a location there is nothing to group on.
- **Embedding model:** open_clip `ViT-B-32` with `laion2b_s34b_b79k` weights, 512 dimensions.
  Changing to a model with other dimensions needs a migration and a re-embed. The worker refuses
  to start if the dimension does not match the schema.
- **Questions are placeholders.** A draft plant gets one queued question with a fixed prompt.
  Claude-drafted, one-tap questions and delivery are milestone 5.
- **Embeddings are computed from `master.jpg`** (orientation-corrected, 2048 px), not the original.

## What was verified, and what was not

Verified here (Linux, Postgres 16 with PostGIS and pgvector):
- All tests pass, including end-to-end worker tests, job-queue behavior (retry, give-up, stuck
  jobs) and a regression test for grouping onto a just-removed plant.
- The real model loads, returns 512-d unit vectors, is deterministic, and takes about 42 ms per
  image on CPU. The worker processed queued photos with it against a real database.

Not verified:
- **Docker.** `infra/worker.Dockerfile` and the compose `worker` service were not built. The
  CPU-only PyTorch install uses `download.pytorch.org`, which was unreachable from the sandbox.
- **Match quality on real garden photos.** The thresholds are untested on real data.
  Synthetic images cannot show how well CLIP separates two tomato plants.

## Running it

```bash
make up        # db + api + worker; the first worker start downloads ~600 MB of weights
make report    # how photos were matched, plus same-plant vs different-plant similarity
```

Set `PLOTWARD_EMBEDDER=histogram` in `.env` for a fast color-only stand-in (no download).
Outside Docker: `make worker`.

## Tuning

`make report` prints, for the photos you have, the similarity between photos of the same plant
and between different plants. Pick the `near` bar above most of "Different plants" and below most
of "Same plant", then set it in `.env` (`PLOTWARD_MATCH_MIN_SIMILARITY_NEAR`, and so on). The
numbers are only as good as the plant assignments, so answer the "What plant is this?" questions
first (the answering flow arrives in milestone 5).
