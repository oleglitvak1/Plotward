import pytest
from plotward_core.db import garden_session
from plotward_core.ingest import UnsupportedImageError, ingest_photo
from plotward_core.models import Job, Photo
from plotward_core.testing import make_exif, make_image_bytes
from sqlalchemy import func, select


def _ingest(session_factory, garden_id, settings, data):
    with garden_session(session_factory, garden_id) as session:
        return ingest_photo(session, settings, data)


def test_jpeg_is_stored_with_metadata_files_and_embed_job(session_factory, garden_id, settings):
    data = make_image_bytes(exif=make_exif())
    result = _ingest(session_factory, garden_id, settings, data)

    assert not result.duplicate
    photo = result.photo
    assert photo.width == 320 and photo.height == 240
    assert photo.captured_at.isoformat() == "2026-11-21T15:30:00-08:00"
    assert photo.exif["Make"] == "TestCam"
    base = settings.data_dir / photo.file_key.rsplit("/", 1)[0]
    assert (settings.data_dir / photo.file_key).read_bytes() == data
    assert (base / "master.jpg").exists() and (base / "thumb.jpg").exists()

    with garden_session(session_factory, garden_id) as session:
        jobs = session.scalars(select(Job)).all()
        assert [(j.kind, j.status) for j in jobs] == [("embed_photo", "queued")]
        assert jobs[0].payload == {"photo_id": str(photo.id)}
        point = session.execute(
            select(func.ST_Y(func.ST_GeomFromEWKB(Photo.gps))).where(Photo.id == photo.id)
        ).scalar_one()
        assert point == pytest.approx(37.7749, abs=1e-3)


def test_heic_is_supported(session_factory, garden_id, settings):
    data = make_image_bytes("HEIF", exif=make_exif())
    result = _ingest(session_factory, garden_id, settings, data)
    assert result.photo.file_key.endswith("original.heic")
    assert result.photo.captured_at is not None
    assert result.photo.exif["Make"] == "TestCam"


def test_same_bytes_twice_is_a_duplicate(session_factory, garden_id, settings):
    data = make_image_bytes()
    first = _ingest(session_factory, garden_id, settings, data)
    second = _ingest(session_factory, garden_id, settings, data)
    assert second.duplicate and second.photo.id == first.photo.id
    with garden_session(session_factory, garden_id) as session:
        assert session.scalar(select(func.count()).select_from(Photo)) == 1
        assert session.scalar(select(func.count()).select_from(Job)) == 1


def test_same_bytes_in_two_gardens_are_two_photos(session_factory, make_garden, settings):
    data = make_image_bytes()
    a, b = make_garden("a"), make_garden("b")
    first = _ingest(session_factory, a, settings, data)
    second = _ingest(session_factory, b, settings, data)
    assert not second.duplicate and first.photo.id != second.photo.id


def test_orientation_is_applied_to_dimensions(session_factory, garden_id, settings):
    data = make_image_bytes(size=(320, 240), exif=make_exif(orientation=6))  # rotated 90 deg
    result = _ingest(session_factory, garden_id, settings, data)
    assert (result.photo.width, result.photo.height) == (240, 320)


def test_missing_exif_still_ingests(session_factory, garden_id, settings):
    result = _ingest(session_factory, garden_id, settings, make_image_bytes())
    assert result.photo.captured_at is None and result.photo.gps is None
    assert result.photo.exif == {}


@pytest.mark.parametrize("data", [b"not an image", b"", make_image_bytes("PNG")])
def test_unsupported_input_is_rejected_and_nothing_is_stored(
    session_factory, garden_id, settings, data
):
    with pytest.raises(UnsupportedImageError):
        _ingest(session_factory, garden_id, settings, data)
    with garden_session(session_factory, garden_id) as session:
        assert session.scalar(select(func.count()).select_from(Photo)) == 0
    assert not (settings.data_dir / "photos").exists()
