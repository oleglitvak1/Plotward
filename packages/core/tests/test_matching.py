from datetime import UTC, datetime, timedelta

import pytest
from matchkit import add_photo, add_plant, at, blend, unit
from plotward_core.db import garden_session
from plotward_core.matching import NEW_PLANT_PROMPT, match_photo
from plotward_core.models import Plant, Question
from sqlalchemy import func, select

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


@pytest.fixture
def run(session_factory, garden_id, settings):
    """Run `fn(session)` in a garden session; returns whatever it returns."""

    def _run(fn):
        with garden_session(session_factory, garden_id) as s:
            return fn(s)

    return _run


def _match(settings, s, photo):
    return match_photo(s, settings, photo)


def test_nearby_plant_with_a_similar_photo_is_matched(run, settings):
    def scenario(s):
        plant = add_plant(s, at(0, 0))
        add_photo(s, embedding=unit(0), point=at(0, 0), plant=plant)
        new = add_photo(s, embedding=blend(0, 1, 0.1), point=at(3, 0))  # cos ~ 0.95
        result = _match(settings, s, new)
        return plant.id, new, result

    plant_id, photo, result = run(scenario)
    assert result.plant_id == plant_id and result.method == "gps_embedding" and not result.created
    assert result.score == pytest.approx(0.949, abs=1e-3)
    assert photo.plant_id == plant_id and photo.match_method == "gps_embedding"


def test_embedding_picks_between_two_plants_in_range(run, settings):
    def scenario(s):
        a, b = add_plant(s, at(0, 0)), add_plant(s, at(0, 6))
        add_photo(s, embedding=unit(0), point=at(0, 0), plant=a)
        add_photo(s, embedding=unit(1), point=at(0, 6), plant=b)
        new = add_photo(s, embedding=blend(1, 5, 0.05), point=at(0, 3))  # looks like b
        return b.id, _match(settings, s, new)

    b_id, result = run(scenario)
    assert result.plant_id == b_id and result.method == "gps_embedding"


def test_two_equally_plausible_plants_are_not_guessed(run, settings):
    def scenario(s):
        a, b = add_plant(s, at(0, 0)), add_plant(s, at(0, 6))
        # The new photo looks almost exactly like both plants' photos (0.995 vs 0.994).
        add_photo(s, embedding=blend(0, 1, 0.01), point=at(0, 0), plant=a)
        add_photo(s, embedding=blend(0, 2, 0.012), point=at(0, 6), plant=b)
        new = add_photo(s, embedding=unit(0), point=at(0, 3))
        return a.id, b.id, _match(settings, s, new)

    a_id, b_id, result = run(scenario)
    assert result.method == "new_plant" and result.created
    assert result.plant_id not in (a_id, b_id)


def test_nearby_plant_that_looks_different_is_not_matched(run, settings):
    def scenario(s):
        plant = add_plant(s, at(0, 0))
        add_photo(s, embedding=unit(0), point=at(0, 0), plant=plant)
        new = add_photo(s, embedding=unit(7), point=at(4, 0))
        return plant.id, _match(settings, s, new)

    plant_id, result = run(scenario)
    assert result.method == "new_plant" and result.plant_id != plant_id


def test_lone_plant_in_range_with_no_photos_is_matched_by_gps_alone(run, settings):
    def scenario(s):
        plant = add_plant(s, at(0, 0))
        new = add_photo(s, embedding=unit(3), point=at(2, 0))
        return plant.id, _match(settings, s, new)

    plant_id, result = run(scenario)
    assert (result.plant_id, result.method, result.score) == (plant_id, "gps_only", None)


def test_plant_outside_the_radius_is_not_a_gps_candidate(run, settings):
    def scenario(s):
        plant = add_plant(s, at(0, 0))
        add_photo(s, embedding=unit(0), point=at(0, 0), plant=plant)
        new = add_photo(s, embedding=unit(0), point=at(60, 0))  # same look, 60 m away
        return plant.id, _match(settings, s, new)

    plant_id, result = run(scenario)
    # Identical embedding still matches, but only through the stricter embedding-only path.
    assert result.plant_id == plant_id and result.method == "embedding"
    assert result.score == pytest.approx(1.0)


def test_photo_without_gps_matches_on_a_strong_embedding(run, settings):
    def scenario(s):
        plant = add_plant(s, at(0, 0))
        add_photo(s, embedding=unit(0), point=at(0, 0), plant=plant)
        strong = add_photo(s, embedding=blend(0, 1, 0.05))  # cos ~ 0.97
        return plant.id, _match(settings, s, strong)

    plant_id, result = run(scenario)
    assert (result.plant_id, result.method) == (plant_id, "embedding")


def test_photo_without_gps_is_not_matched_on_a_middling_embedding(run, settings):
    def scenario(s):
        plant = add_plant(s, at(0, 0))
        add_photo(s, embedding=unit(0), point=at(0, 0), plant=plant)
        weak = add_photo(s, embedding=blend(0, 1, 0.3))  # cos ~ 0.84, under the 0.85 bar
        return plant.id, _match(settings, s, weak)

    plant_id, result = run(scenario)
    assert result.method == "new_plant" and result.plant_id != plant_id


def test_removed_plants_are_never_candidates(run, settings):
    def scenario(s):
        gone = add_plant(s, at(0, 0), status="removed", kind="annual")
        add_photo(s, embedding=unit(0), point=at(0, 0), plant=gone)
        new = add_photo(s, embedding=unit(0), point=at(0, 0))  # next year's tomato, same spot
        return gone.id, _match(settings, s, new)

    gone_id, result = run(scenario)
    assert result.method == "new_plant" and result.plant_id != gone_id


def test_only_the_most_recent_photos_count(run, settings):
    def scenario(s):
        plant = add_plant(s, at(0, 0))
        # The seedling photo looks like the new photo; the five latest do not.
        add_photo(s, embedding=unit(0), point=at(0, 0), plant=plant, when=T0)
        for k in range(5):
            add_photo(
                s,
                embedding=unit(10 + k),
                point=at(0, 0),
                plant=plant,
                when=T0 + timedelta(days=30 + k),
            )
        new = add_photo(s, embedding=unit(0), point=at(1, 0), when=T0 + timedelta(days=60))
        return plant.id, _match(settings, s, new)

    plant_id, result = run(scenario)
    assert result.method == "new_plant" and result.plant_id != plant_id


def test_a_quick_pass_along_a_bed_makes_one_draft_not_many(run, settings):
    def scenario(s):
        first = add_photo(s, embedding=unit(0), point=at(0, 0), when=T0)
        s.refresh(first)  # as the worker sees it: gps is a database geometry, not a string
        r1 = _match(settings, s, first)
        second = add_photo(s, embedding=unit(9), point=at(3, 0), when=T0 + timedelta(seconds=20))
        r2 = _match(settings, s, second)
        s.flush()
        return r1, r2, s.scalar(select(func.count()).select_from(Plant))

    r1, r2, plants = run(scenario)
    assert r1.method == "new_plant" and r2.method == "grouped"
    assert r2.plant_id == r1.plant_id and plants == 1


def test_photos_far_apart_in_time_or_space_start_separate_drafts(run, settings):
    def scenario(s):
        a = add_photo(s, embedding=unit(0), point=at(0, 0), when=T0)
        _match(settings, s, a)
        later = add_photo(s, embedding=unit(9), point=at(3, 0), when=T0 + timedelta(minutes=5))
        farther = add_photo(s, embedding=unit(8), point=at(30, 0), when=T0 + timedelta(seconds=10))
        _match(settings, s, later)
        _match(settings, s, farther)
        s.flush()
        return s.scalar(select(func.count()).select_from(Plant))

    assert run(scenario) == 3


def test_a_new_plant_queues_exactly_one_question(run, settings):
    def scenario(s):
        p1 = add_photo(s, embedding=unit(0), point=at(0, 0), when=T0)
        r1 = _match(settings, s, p1)
        p2 = add_photo(s, embedding=unit(9), point=at(3, 0), when=T0 + timedelta(seconds=5))
        _match(settings, s, p2)  # grouped: no second question
        s.flush()
        return r1.plant_id, s.scalars(select(Question)).all()

    plant_id, questions = run(scenario)
    assert len(questions) == 1
    q = questions[0]
    assert (q.target_type, q.target_id, q.status, q.prompt) == (
        "plant",
        plant_id,
        "queued",
        NEW_PLANT_PROMPT,
    )


def test_matching_needs_an_embedding(run, settings):
    def scenario(s):
        photo = add_photo(s, embedding=None, point=at(0, 0))
        with pytest.raises(ValueError):
            _match(settings, s, photo)

    run(scenario)


def test_a_photo_taken_moments_after_pulling_a_plant_does_not_join_it(run, settings):
    def scenario(s):
        gone = add_plant(s, at(0, 0), status="removed", kind="annual")
        add_photo(s, embedding=unit(0), point=at(0, 0), plant=gone, when=T0)
        new = add_photo(s, embedding=unit(0), point=at(1, 0), when=T0 + timedelta(seconds=10))
        return gone.id, _match(settings, s, new)

    gone_id, result = run(scenario)
    assert result.method == "new_plant" and result.plant_id != gone_id
