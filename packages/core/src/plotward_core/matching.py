"""Attach a freshly embedded photo to a plant, or start a new draft plant.

Order of evidence (see docs/architecture.md, flow 1):
  1. GPS first: living plants within `match_radius_m`. Embedding similarity to each plant's
     most recent photos picks between them.
  2. No usable GPS candidate: embedding similarity against all living plants, with a stricter bar.
  3. Still no match: if another photo was taken a moment ago and a few meters away, treat this as
     the same pass past the same plant. Otherwise create a draft plant and queue a question.

Every decision is recorded on the photo (`match_method`, `match_score`) so accuracy can be
measured. The thresholds are starting guesses; tune them on real photos.
"""

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Literal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, aliased

from .config import Settings
from .models import Photo, Plant, Question

Method = Literal["gps_embedding", "gps_only", "embedding", "grouped", "new_plant"]
NEW_PLANT_PROMPT = "What plant is this?"


@dataclass(frozen=True)
class MatchResult:
    plant_id: object
    method: Method
    score: float | None
    created: bool


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


def _when(photo: Photo):
    return photo.captured_at or photo.received_at


def _plant_score(session: Session, settings: Settings, plant_id, photo: Photo) -> float | None:
    """Best similarity between `photo` and the plant's most recent photos. None if the plant has
    no embedded photos yet."""
    recent = session.scalars(
        select(Photo.embedding)
        .where(
            Photo.plant_id == plant_id,
            Photo.id != photo.id,
            Photo.embedding.is_not(None),
        )
        .order_by(func.coalesce(Photo.captured_at, Photo.received_at).desc())
        .limit(settings.match_recent_photos)
    ).all()
    if not recent:
        return None
    return max(cosine(list(photo.embedding), list(vec)) for vec in recent)


def _pick(scores: dict, threshold: float, margin: float) -> tuple[object, float] | None:
    """Best plant whose score clears the bar and beats the runner-up by `margin`."""
    ranked = sorted(
        ((pid, s) for pid, s in scores.items() if s is not None), key=lambda x: x[1], reverse=True
    )
    if not ranked or ranked[0][1] < threshold:
        return None
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < margin:
        return None
    return ranked[0]


def _nearby_living_plants(session: Session, photo: Photo, radius_m: float) -> list:
    return list(
        session.scalars(
            select(Plant.id)
            .join(Photo, Photo.id == photo.id)
            .where(
                Plant.status != "removed",
                Plant.location.is_not(None),
                func.ST_DWithin(Plant.location, Photo.gps, radius_m),
            )
        )
    )


def _grouped_plant(session: Session, settings: Settings, photo: Photo):
    """Plant of another photo taken within the group window and radius, if any."""
    window = timedelta(seconds=settings.group_window_s)
    this = _when(photo)
    me = aliased(Photo)
    when = func.coalesce(Photo.captured_at, Photo.received_at)
    return session.scalars(
        select(Photo.plant_id)
        .join(me, me.id == photo.id)
        .join(Plant, Plant.id == Photo.plant_id)
        .where(
            Photo.id != photo.id,
            Plant.status != "removed",
            Photo.gps.is_not(None),
            when >= this - window,
            when <= this + window,
            func.ST_DWithin(Photo.gps, me.gps, settings.group_radius_m),
        )
        .order_by(func.abs(func.extract("epoch", when - this)))
        .limit(1)
    ).first()


def _attach(photo: Photo, plant_id, method: Method, score: float | None) -> MatchResult:
    photo.plant_id, photo.match_method, photo.match_score = plant_id, method, score
    return MatchResult(plant_id, method, score, created=False)


def match_photo(session: Session, settings: Settings, photo: Photo) -> MatchResult:
    """Decide which plant `photo` shows. Requires `photo.embedding`. The caller commits."""
    if photo.embedding is None:
        raise ValueError("photo has no embedding yet")

    # 1. GPS candidates, then embeddings to choose among them.
    if photo.gps is not None:
        near = _nearby_living_plants(session, photo, settings.match_radius_m)
        if near:
            scores = {pid: _plant_score(session, settings, pid, photo) for pid in near}
            picked = _pick(scores, settings.match_min_similarity_near, settings.match_margin)
            if picked:
                return _attach(photo, picked[0], "gps_embedding", picked[1])
            # A lone plant in range with no photo evidence yet: GPS is all we have.
            if len(near) == 1 and scores[near[0]] is None:
                return _attach(photo, near[0], "gps_only", None)

    # 2. No (usable) GPS candidate: embeddings alone, with a stricter bar.
    living = list(session.scalars(select(Plant.id).where(Plant.status != "removed")))
    if living:
        scores = {pid: _plant_score(session, settings, pid, photo) for pid in living}
        picked = _pick(scores, settings.match_min_similarity_far, settings.match_margin)
        if picked:
            return _attach(photo, picked[0], "embedding", picked[1])

    # 3. One pass along a bed: same moment, same spot, same plant.
    if photo.gps is not None:
        plant_id = _grouped_plant(session, settings, photo)
        if plant_id is not None:
            return _attach(photo, plant_id, "grouped", None)

    # 4. Nothing fits: a new draft plant, and a question for you.
    plant = Plant(status="draft")
    session.add(plant)
    session.flush()
    # Copy the location inside the database: a photo loaded from Postgres holds a binary
    # geometry, and converting that in Python would need the optional shapely dependency.
    session.execute(
        update(Plant)
        .where(Plant.id == plant.id)
        .values(location=select(Photo.gps).where(Photo.id == photo.id).scalar_subquery())
    )
    session.add(
        Question(target_type="plant", target_id=plant.id, prompt=NEW_PLANT_PROMPT, options=[])
    )
    result = _attach(photo, plant.id, "new_plant", None)
    return MatchResult(result.plant_id, result.method, result.score, created=True)
