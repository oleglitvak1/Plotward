import itertools

import pytest
from geoalchemy2 import Geometry
from plotward_core.db import garden_session
from plotward_core.ingest import ingest_photo
from plotward_core.models import Job, Photo, Plant, Question
from plotward_core.testing import make_exif, make_image_bytes
from plotward_ml import ColorHistogramEmbedder
from plotward_worker.runner import run_once
from sqlalchemy import cast, func, select, text

LAT, LON = 37.7749, -122.4194
GREEN, RED = (30, 160, 50), (200, 30, 30)
_sizes = itertools.count(100)  # different pixel sizes give different bytes, hence different hashes


def photo_bytes(color, *, north_m=0.0, minute=0):
    taken = f"2026:06:01 10:{minute:02d}:00"
    exif = make_exif(lat=LAT + north_m / 111_000, lon=LON, taken=taken, offset="+00:00")
    return make_image_bytes(color=color, size=(next(_sizes), 80), exif=exif)


@pytest.fixture
def embedder():
    return ColorHistogramEmbedder()


@pytest.fixture
def upload(session_factory, garden_id, settings):
    def _upload(data):
        with garden_session(session_factory, garden_id) as s:
            return ingest_photo(s, settings, data).photo.id

    return _upload


def drain(session_factory, settings, embedder):
    n = 0
    while run_once(session_factory, settings, embedder):
        n += 1
    return n


def photo_row(session_factory, garden_id, photo_id):
    with garden_session(session_factory, garden_id) as s:
        p = s.get(Photo, photo_id)
        return p.plant_id, p.match_method, p.embedding_model


def count(session_factory, garden_id, model):
    with garden_session(session_factory, garden_id) as s:
        return s.scalar(select(func.count()).select_from(model))


def job_statuses(session_factory):
    with session_factory() as s:
        return [r[0] for r in s.execute(text("select status from job order by created_at"))]


def test_first_photo_creates_a_draft_plant_and_a_question(
    session_factory, garden_id, settings, embedder, upload
):
    photo_id = upload(photo_bytes(GREEN))
    assert drain(session_factory, settings, embedder) == 1

    plant_id, method, model = photo_row(session_factory, garden_id, photo_id)
    assert (method, model) == ("new_plant", "color-histogram")
    assert plant_id is not None
    assert count(session_factory, garden_id, Plant) == 1
    assert count(session_factory, garden_id, Question) == 1
    assert job_statuses(session_factory) == ["done"]
    with garden_session(session_factory, garden_id) as s:
        lat, lon = s.execute(
            select(
                func.ST_Y(cast(Plant.location, Geometry)), func.ST_X(cast(Plant.location, Geometry))
            )
        ).one()
    assert (lat, lon) == pytest.approx((LAT, LON), abs=1e-4)  # the draft sits where the photo was


def test_a_later_photo_of_the_same_plant_attaches_to_it(
    session_factory, garden_id, settings, embedder, upload
):
    first = upload(photo_bytes(GREEN, minute=0))
    drain(session_factory, settings, embedder)
    second = upload(photo_bytes(GREEN, north_m=2, minute=30))  # half an hour later, 2 m away
    drain(session_factory, settings, embedder)

    plant_1, _, _ = photo_row(session_factory, garden_id, first)
    plant_2, method, _ = photo_row(session_factory, garden_id, second)
    assert plant_2 == plant_1 and method == "gps_embedding"
    assert count(session_factory, garden_id, Plant) == 1
    assert count(session_factory, garden_id, Question) == 1


def test_a_different_looking_plant_nearby_becomes_its_own_plant(
    session_factory, garden_id, settings, embedder, upload
):
    first = upload(photo_bytes(GREEN, minute=0))
    drain(session_factory, settings, embedder)
    second = upload(photo_bytes(RED, north_m=3, minute=30))
    drain(session_factory, settings, embedder)

    plant_1, _, _ = photo_row(session_factory, garden_id, first)
    plant_2, method, _ = photo_row(session_factory, garden_id, second)
    assert plant_2 != plant_1 and method == "new_plant"
    assert count(session_factory, garden_id, Plant) == 2


def test_running_the_same_job_twice_changes_nothing(
    session_factory, garden_id, settings, embedder, upload
):
    from plotward_worker.handlers import handle_embed_photo

    upload(photo_bytes(GREEN))
    with session_factory() as s:
        s.execute(text("update job set status = 'queued'"))  # as if it had to be redelivered
        s.commit()
    drain(session_factory, settings, embedder)
    from plotward_core.jobs import ClaimedJob

    with garden_session(session_factory, garden_id) as s:
        job = s.scalars(select(Job)).one()
        again = ClaimedJob(job.id, garden_id, job.kind, job.payload, 2)
    handle_embed_photo(session_factory, settings, embedder, again)
    assert count(session_factory, garden_id, Plant) == 1
    assert count(session_factory, garden_id, Question) == 1


def test_a_missing_photo_fails_permanently(session_factory, garden_id, settings, embedder):
    with garden_session(session_factory, garden_id) as s:
        s.add(Job(kind="embed_photo", payload={"photo_id": "00000000-0000-0000-0000-000000000000"}))
    drain(session_factory, settings, embedder)
    assert job_statuses(session_factory) == ["failed"]


def test_an_unknown_job_kind_fails_permanently(session_factory, garden_id, settings, embedder):
    with garden_session(session_factory, garden_id) as s:
        s.add(Job(kind="mystery"))
    drain(session_factory, settings, embedder)
    assert job_statuses(session_factory) == ["failed"]


def test_a_crashing_embedder_leaves_the_job_queued_for_retry(
    session_factory, garden_id, settings, upload
):
    class Exploding(ColorHistogramEmbedder):
        def embed(self, data):
            raise RuntimeError("model fell over")

    upload(photo_bytes(GREEN))
    drain(session_factory, settings, Exploding())

    with session_factory() as s:
        status, error = s.execute(text("select status, last_error from job")).one()
    assert status == "queued" and "model fell over" in error
    assert count(session_factory, garden_id, Plant) == 0  # nothing half-done was committed


def test_an_embedder_with_the_wrong_dimension_is_rejected(
    session_factory, garden_id, settings, upload
):
    class Wrong(ColorHistogramEmbedder):
        def embed(self, data):
            return [1.0, 0.0]

    upload(photo_bytes(GREEN))
    drain(session_factory, settings, Wrong())
    assert job_statuses(session_factory) == ["failed"]


def test_report_summarizes_matching(session_factory, garden_id, settings, embedder, upload):
    from plotward_worker.report import build_report

    upload(photo_bytes(GREEN, minute=0))
    upload(photo_bytes(GREEN, north_m=2, minute=30))
    upload(photo_bytes(RED, north_m=40, minute=45))
    drain(session_factory, settings, embedder)
    with garden_session(session_factory, garden_id) as s:
        report = build_report(s, settings)
    assert "3 photos, 2 plants" in report
    assert "gps_embedding=1" in report and "new_plant=2" in report
    assert "Same plant:       n=1" in report and "Different plants: n=2" in report
