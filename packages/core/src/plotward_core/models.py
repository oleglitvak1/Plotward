"""SQLAlchemy models. Every table except `garden` carries `garden_id` via GardenScoped."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geography
from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

# open_clip ViT-B/32 produces 512-d vectors. Changing the embedding model means a migration.
EMBEDDING_DIM = 512


class Base(DeclarativeBase):
    pass


class GardenScoped:
    """Mixin: the tenant column. Sessions filter on it automatically (see scoping.py)."""

    @declared_attr
    def garden_id(cls) -> Mapped[uuid.UUID]:
        return mapped_column(
            Uuid, ForeignKey("garden.id", ondelete="CASCADE"), nullable=False, index=True
        )


def _pk() -> Mapped[uuid.UUID]:
    return mapped_column(Uuid, primary_key=True, default=uuid.uuid4)


def _created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Garden(Base):
    __tablename__ = "garden"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200))
    timezone: Mapped[str] = mapped_column(String(64), default="UTC")
    home_location: Mapped[Any | None] = mapped_column(Geography("POINT", srid=4326))
    created_at: Mapped[datetime] = _created()


class Zone(GardenScoped, Base):
    __tablename__ = "zone"

    id: Mapped[uuid.UUID] = _pk()
    name: Mapped[str] = mapped_column(String(200))
    polygon: Mapped[Any | None] = mapped_column(Geography("POLYGON", srid=4326))
    created_at: Mapped[datetime] = _created()


class Plant(GardenScoped, Base):
    __tablename__ = "plant"
    __table_args__ = (
        CheckConstraint("status in ('draft', 'active', 'removed')", name="plant_status_valid"),
        CheckConstraint("kind is null or kind in ('perennial', 'annual')", name="plant_kind_valid"),
        # A plant is removed exactly when it has an end date. Only living plants are match
        # candidates, so next season's planting in the same spot is a new plant.
        CheckConstraint(
            "(status = 'removed') = (ended_on is not null)", name="plant_end_matches_status"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    zone_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("zone.id", ondelete="SET NULL")
    )
    species: Mapped[str | None] = mapped_column(String(200))
    cultivar: Mapped[str | None] = mapped_column(String(200))
    # perennial (trees, shrubs) or annual (tomatoes); null until known, e.g. a draft plant.
    kind: Mapped[str | None] = mapped_column(String(16))
    planted_date: Mapped[date | None] = mapped_column(Date)
    ended_on: Mapped[date | None] = mapped_column(Date)
    location: Mapped[Any | None] = mapped_column(Geography("POINT", srid=4326))
    status: Mapped[str] = mapped_column(String(16), default="draft", server_default="draft")
    created_at: Mapped[datetime] = _created()


class Photo(GardenScoped, Base):
    __tablename__ = "photo"
    __table_args__ = (
        UniqueConstraint("garden_id", "content_hash", name="photo_garden_content_hash_key"),
        CheckConstraint("storage_tier in ('hot', 'cold')", name="photo_storage_tier_valid"),
        CheckConstraint(
            "match_method is null or match_method in "
            "('gps_embedding', 'gps_only', 'embedding', 'grouped', 'new_plant', 'user')",
            name="photo_match_method_valid",
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    plant_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("plant.id", ondelete="SET NULL"), index=True
    )
    # From EXIF; null when the file has no capture time. received_at is the server clock.
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    exif: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    gps: Mapped[Any | None] = mapped_column(Geography("POINT", srid=4326))
    # Relative path of the original under the data dir. Photos are identified by content_hash.
    file_key: Mapped[str] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(String(64))
    byte_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    embedding: Mapped[Any | None] = mapped_column(Vector(EMBEDDING_DIM))
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    embedding_version: Mapped[str | None] = mapped_column(String(50))
    storage_tier: Mapped[str] = mapped_column(String(8), default="hot", server_default="hot")
    # How the photo got its plant, so match accuracy can be measured later.
    match_method: Mapped[str | None] = mapped_column(String(24))
    match_score: Mapped[float | None] = mapped_column(Float)


class Label(GardenScoped, Base):
    """Append-only verified facts. A user label outranks a model label."""

    __tablename__ = "label"
    __table_args__ = (
        CheckConstraint("source in ('user', 'model')", name="label_source_valid"),
        CheckConstraint("target_type in ('plant', 'photo')", name="label_target_type_valid"),
        Index("label_target_idx", "garden_id", "target_type", "target_id", "field"),
    )

    id: Mapped[uuid.UUID] = _pk()
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    field: Mapped[str] = mapped_column(String(100))
    value: Mapped[Any] = mapped_column(JSONB)
    source: Mapped[str] = mapped_column(String(8))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class CareEvent(GardenScoped, Base):
    __tablename__ = "care_event"

    id: Mapped[uuid.UUID] = _pk()
    plant_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("plant.id", ondelete="CASCADE"), index=True
    )
    type: Mapped[str] = mapped_column(String(32))  # water, prune, fertilize, ...
    occurred_on: Mapped[date] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Question(GardenScoped, Base):
    __tablename__ = "question"
    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'asked', 'answered', 'skipped')", name="question_status_valid"
        ),
    )

    id: Mapped[uuid.UUID] = _pk()
    target_type: Mapped[str] = mapped_column(String(16))
    target_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    prompt: Mapped[str] = mapped_column(Text)
    options: Mapped[list[Any]] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued")
    asked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created()


class ModelCall(GardenScoped, Base):
    __tablename__ = "model_call"

    id: Mapped[uuid.UUID] = _pk()
    feature: Mapped[str] = mapped_column(String(64), index=True)
    model: Mapped[str] = mapped_column(String(100))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(Numeric(12, 6), default=Decimal(0))
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    model_tier: Mapped[str | None] = mapped_column(String(32))
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = _created()


class Job(GardenScoped, Base):
    """Postgres-backed job queue. Workers claim rows with FOR UPDATE SKIP LOCKED."""

    __tablename__ = "job"
    __table_args__ = (
        CheckConstraint(
            "status in ('queued', 'running', 'done', 'failed')", name="job_status_valid"
        ),
        Index("job_claim_idx", "status", "run_after"),
    )

    id: Mapped[uuid.UUID] = _pk()
    kind: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    run_after: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
