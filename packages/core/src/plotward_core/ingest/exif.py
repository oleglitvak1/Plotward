"""EXIF extraction. Raw EXIF is kept as JSON so matching can be redone later."""

import base64
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from PIL import ExifTags, Image
from PIL.TiffImagePlugin import IFDRational

EXIF_IFD = 0x8769
GPS_IFD = 0x8825


@dataclass(frozen=True)
class ParsedExif:
    raw: dict[str, Any]
    captured_at: datetime | None
    latitude: float | None
    longitude: float | None


def _json_safe(value: Any) -> Any:
    if isinstance(value, IFDRational):
        return float(value) if value.denominator else None
    if isinstance(value, bytes):
        text = value.rstrip(b"\x00")
        try:
            return text.decode("ascii")
        except UnicodeDecodeError:
            return {"base64": base64.b64encode(value[:256]).decode("ascii"), "bytes": len(value)}
    if isinstance(value, str):
        return value.replace("\x00", "")
    if isinstance(value, tuple | list):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, int | float | bool) or value is None:
        if isinstance(value, float) and value != value:  # NaN
            return None
        return value
    return str(value)


def _named(ifd: Any, names: dict[int, str]) -> dict[str, Any]:
    return {names.get(tag, str(tag)): _json_safe(val) for tag, val in dict(ifd).items()}


def _dms_to_degrees(dms: Any, ref: str | None) -> float | None:
    try:
        d, m, s = (float(x) for x in dms)
    except (TypeError, ValueError):
        return None
    degrees = d + m / 60 + s / 3600
    return -degrees if ref in ("S", "W") else degrees


def _parse_offset(text: str | None) -> timezone | None:
    if not text or len(text) < 6 or text[0] not in "+-" or text[3] != ":":
        return None
    try:
        delta = timedelta(hours=int(text[1:3]), minutes=int(text[4:6]))
    except ValueError:
        return None
    return timezone(-delta if text[0] == "-" else delta)


def _captured_at(raw: dict[str, Any], garden_tz: str) -> datetime | None:
    text = raw.get("DateTimeOriginal") or raw.get("DateTimeDigitized") or raw.get("DateTime")
    if not isinstance(text, str):
        return None
    try:
        naive = datetime.strptime(text.strip(), "%Y:%m:%d %H:%M:%S")
    except ValueError:
        return None
    tz = _parse_offset(raw.get("OffsetTimeOriginal") or raw.get("OffsetTime"))
    if tz is None:
        try:
            tz = ZoneInfo(garden_tz)
        except ZoneInfoNotFoundError:
            tz = UTC
    return naive.replace(tzinfo=tz)


def parse_exif(image: Image.Image, garden_tz: str = "UTC") -> ParsedExif:
    exif = image.getexif()
    raw: dict[str, Any] = _named(exif, ExifTags.TAGS)
    raw.pop("ExifOffset", None)
    raw.pop("GPSInfo", None)
    raw.update(_named(exif.get_ifd(EXIF_IFD), ExifTags.TAGS))
    gps_raw = _named(exif.get_ifd(GPS_IFD), ExifTags.GPSTAGS)
    if gps_raw:
        raw["GPS"] = gps_raw

    lat = lon = None
    if "GPSLatitude" in gps_raw and "GPSLongitude" in gps_raw:
        lat = _dms_to_degrees(gps_raw["GPSLatitude"], gps_raw.get("GPSLatitudeRef"))
        lon = _dms_to_degrees(gps_raw["GPSLongitude"], gps_raw.get("GPSLongitudeRef"))
        if lat is None or lon is None or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            lat = lon = None
        elif lat == 0 and lon == 0:  # cameras write 0,0 when there is no fix
            lat = lon = None

    return ParsedExif(raw, _captured_at(raw, garden_tz), lat, lon)
