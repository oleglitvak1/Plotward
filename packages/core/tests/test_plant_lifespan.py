from datetime import date

import pytest
from plotward_core.db import garden_session
from plotward_core.models import Plant
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError


def _add(session_factory, garden_id, **fields):
    with garden_session(session_factory, garden_id) as s:
        plant = Plant(**fields)
        s.add(plant)
    return plant


def test_annual_and_perennial_plants_are_accepted(session_factory, garden_id):
    _add(session_factory, garden_id, species="apple", kind="perennial", status="active")
    _add(session_factory, garden_id, species="tomato", kind="annual", status="active")
    _add(session_factory, garden_id, status="draft")  # kind unknown yet
    with garden_session(session_factory, garden_id) as s:
        kinds = sorted(p.kind or "" for p in s.scalars(select(Plant)))
    assert kinds == ["", "annual", "perennial"]


def test_unknown_kind_is_rejected(session_factory, garden_id):
    with pytest.raises(IntegrityError):
        _add(session_factory, garden_id, kind="biennial")


def test_removed_plant_needs_an_end_date(session_factory, garden_id):
    with pytest.raises(IntegrityError):
        _add(session_factory, garden_id, kind="annual", status="removed")


def test_living_plant_cannot_have_an_end_date(session_factory, garden_id):
    with pytest.raises(IntegrityError):
        _add(session_factory, garden_id, status="active", ended_on=date(2026, 10, 1))


def test_pulled_tomato_ends_and_next_years_plant_is_separate(session_factory, garden_id):
    old = _add(session_factory, garden_id, species="tomato", kind="annual", status="active")
    with garden_session(session_factory, garden_id) as s:
        plant = s.get(Plant, old.id)
        plant.status, plant.ended_on = "removed", date(2026, 10, 15)
    new = _add(session_factory, garden_id, species="tomato", kind="annual", status="active")
    with garden_session(session_factory, garden_id) as s:
        living = s.scalars(select(Plant).where(Plant.status != "removed")).all()
    assert [p.id for p in living] == [new.id]
