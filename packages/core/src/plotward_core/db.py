import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from . import scoping
from .config import Settings, get_settings
from .models import Garden


@lru_cache
def get_engine(database_url: str | None = None) -> Engine:
    return create_engine(database_url or get_settings().database_url, pool_pre_ping=True)


def make_session_factory(engine: Engine | None = None) -> sessionmaker[Session]:
    return sessionmaker(engine or get_engine(), expire_on_commit=False)


@contextmanager
def garden_session(factory: sessionmaker[Session], garden_id: uuid.UUID) -> Iterator[Session]:
    """A session whose queries are filtered to one garden. Commits on success."""
    with factory() as session:
        scoping.bind_garden(session, garden_id)
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise


def ensure_default_garden(factory: sessionmaker[Session], settings: Settings) -> uuid.UUID:
    """Single-user PoC: use the first garden, creating it on first run."""
    with factory() as session:
        garden = session.scalars(select(Garden).order_by(Garden.created_at).limit(1)).first()
        if garden is None:
            garden = Garden(name=settings.garden_name, timezone=settings.garden_timezone)
            session.add(garden)
            session.commit()
        return garden.id
