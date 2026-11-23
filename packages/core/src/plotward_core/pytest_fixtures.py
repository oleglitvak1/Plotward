"""Shared pytest fixtures: a migrated test database and garden helpers. Test-only module."""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError

from plotward_core.config import Settings
from plotward_core.db import make_session_factory
from plotward_core.models import Garden

TEST_DB_URL = os.environ.get(
    "PLOTWARD_TEST_DATABASE_URL",
    "postgresql+psycopg://plotward:plotward@localhost:5432/plotward_test",
)
ALEMBIC_INI = Path(__file__).resolve().parents[4] / "infra" / "alembic.ini"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL)
    try:
        with eng.begin() as conn:
            conn.execute(text("drop schema public cascade"))
            conn.execute(text("create schema public"))
    except OperationalError:
        pytest.skip("test Postgres is not reachable; set PLOTWARD_TEST_DATABASE_URL")
    # Build the schema with the real migrations, so they are tested too.
    subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(ALEMBIC_INI), "upgrade", "head"],
        check=True,
        env={**os.environ, "PLOTWARD_DATABASE_URL": TEST_DB_URL},
    )
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    factory = make_session_factory(engine)
    yield factory
    with engine.begin() as conn:
        conn.execute(
            text(
                "truncate garden, zone, plant, photo, label, care_event, question, "
                "model_call, job restart identity cascade"
            )
        )


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        database_url=TEST_DB_URL, data_dir=tmp_path / "data", api_key="test-key", max_upload_mb=1
    )


@pytest.fixture
def make_garden(session_factory):
    def _make(name: str = "Test garden", timezone: str = "America/Los_Angeles") -> uuid.UUID:
        with session_factory() as session:
            garden = Garden(name=name, timezone=timezone)
            session.add(garden)
            session.commit()
            return garden.id

    return _make


@pytest.fixture
def garden_id(make_garden) -> uuid.UUID:
    return make_garden()
