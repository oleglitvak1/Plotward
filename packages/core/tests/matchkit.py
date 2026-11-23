"""Builders for matching tests: plants and photos at chosen places with chosen embeddings."""

import itertools
import math
import uuid
from datetime import UTC, date, datetime, timedelta

from plotward_core.models import EMBEDDING_DIM, Photo, Plant

LAT, LON = 37.7749, -122.4194
_days = itertools.count()  # default capture times a day apart, so photos never group by accident
M = 1 / 111_000  # one meter in degrees of latitude


def at(north_m: float = 0.0, east_m: float = 0.0) -> str:
    """EWKT point `north_m`/`east_m` meters from the origin."""
    return f"SRID=4326;POINT({LON + east_m * M * 1.26} {LAT + north_m * M})"


def unit(i: int) -> list[float]:
    v = [0.0] * EMBEDDING_DIM
    v[i] = 1.0
    return v


def blend(i: int, j: int, w: float = 0.5) -> list[float]:
    """Unit vector between axes i and j; cosine with unit(i) is sqrt(1-w), with unit(j) sqrt(w)."""
    v = [0.0] * EMBEDDING_DIM
    v[i], v[j] = math.sqrt(1 - w), math.sqrt(w)
    return v


def add_plant(session, point: str | None = None, status: str = "active", **fields) -> Plant:
    if status == "removed":
        fields.setdefault("ended_on", date(2026, 10, 1))
    plant = Plant(location=point, status=status, **fields)
    session.add(plant)
    session.flush()
    return plant


def add_photo(
    session,
    *,
    embedding: list[float] | None,
    point: str | None = None,
    plant: Plant | None = None,
    when: datetime | None = None,
) -> Photo:
    photo = Photo(
        plant_id=plant.id if plant else None,
        captured_at=when or datetime(2026, 1, 1, 12, 0, tzinfo=UTC) + timedelta(days=next(_days)),
        gps=point,
        embedding=embedding,
        file_key="x",
        content_hash=uuid.uuid4().hex + uuid.uuid4().hex,
        byte_size=1,
        width=1,
        height=1,
    )
    session.add(photo)
    session.flush()
    return photo
