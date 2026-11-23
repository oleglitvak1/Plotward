"""Helpers for building test images with EXIF. Used by the core and API tests."""

import io

import pillow_heif
from PIL import Image

pillow_heif.register_heif_opener()

# 37 deg 46' 29.7" N, 122 deg 25' 9.8" W (San Francisco)
SF_LAT = 37 + 46 / 60 + 29.7 / 3600
SF_LON = -(122 + 25 / 60 + 9.8 / 3600)


def _dms(value: float) -> tuple[float, float, float]:
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60)
    return float(d), float(m), (value - d - m / 60) * 3600


def make_exif(
    *,
    lat: float | None = None,
    lon: float | None = None,
    taken: str | None = "2026:11:21 15:30:00",
    offset: str | None = "-08:00",
    gps: tuple[tuple[float, float, float], str, tuple[float, float, float], str] | None = (
        (37.0, 46.0, 29.7),
        "N",
        (122.0, 25.0, 9.8),
        "W",
    ),
    orientation: int | None = None,
) -> Image.Exif:
    if lat is not None and lon is not None:
        gps = (_dms(lat), "N" if lat >= 0 else "S", _dms(lon), "E" if lon >= 0 else "W")
    exif = Image.Exif()
    exif[0x010F] = "TestCam"  # Make
    if orientation is not None:
        exif[0x0112] = orientation
    exif_ifd = exif.get_ifd(0x8769)
    if taken:
        exif_ifd[36867] = taken  # DateTimeOriginal
    if offset:
        exif_ifd[36881] = offset  # OffsetTimeOriginal
    if gps:
        lat, lat_ref, lon, lon_ref = gps
        gps_ifd = exif.get_ifd(0x8825)
        gps_ifd[1], gps_ifd[2], gps_ifd[3], gps_ifd[4] = lat_ref, lat, lon_ref, lon
    return exif


def make_image_bytes(
    fmt: str = "JPEG",
    *,
    size: tuple[int, int] = (320, 240),
    color: tuple[int, int, int] = (40, 120, 50),
    exif: Image.Exif | None = None,
) -> bytes:
    """Encode a solid-color image. Different `color` values give different content hashes."""
    image = Image.new("RGB", size, color)
    buf = io.BytesIO()
    kwargs = {"exif": exif} if exif is not None else {}
    image.save(buf, fmt, **kwargs)
    return buf.getvalue()
