import io
from datetime import timedelta

import pytest
from PIL import Image
from plotward_core.ingest.exif import parse_exif
from plotward_core.testing import SF_LAT, SF_LON, make_exif, make_image_bytes


def _parse(data: bytes, tz: str = "America/Los_Angeles"):
    return parse_exif(Image.open(io.BytesIO(data)), tz)


def test_gps_and_capture_time_with_offset():
    parsed = _parse(make_image_bytes(exif=make_exif()))
    assert parsed.latitude == pytest.approx(SF_LAT)
    assert parsed.longitude == pytest.approx(SF_LON)
    assert parsed.captured_at.utcoffset() == timedelta(hours=-8)
    assert parsed.captured_at.isoformat() == "2026-11-21T15:30:00-08:00"


def test_capture_time_without_offset_uses_garden_timezone():
    parsed = _parse(make_image_bytes(exif=make_exif(offset=None)), tz="Europe/Berlin")
    assert parsed.captured_at.utcoffset() == timedelta(hours=1)  # CET in November


def test_no_exif_at_all():
    parsed = _parse(make_image_bytes())
    assert parsed.captured_at is None
    assert parsed.latitude is None and parsed.longitude is None


def test_zero_zero_gps_is_treated_as_no_fix():
    zero = ((0.0, 0.0, 0.0), "N", (0.0, 0.0, 0.0), "E")
    parsed = _parse(make_image_bytes(exif=make_exif(gps=zero)))
    assert parsed.latitude is None and parsed.longitude is None


def test_raw_exif_is_json_serializable_and_kept():
    import json

    parsed = _parse(make_image_bytes(exif=make_exif()))
    json.dumps(parsed.raw)
    assert parsed.raw["Make"] == "TestCam"
    assert parsed.raw["DateTimeOriginal"] == "2026:11:21 15:30:00"
    assert parsed.raw["GPS"]["GPSLatitudeRef"] == "N"


def test_garbage_timestamp_is_ignored():
    parsed = _parse(make_image_bytes(exif=make_exif(taken="not a date")))
    assert parsed.captured_at is None
