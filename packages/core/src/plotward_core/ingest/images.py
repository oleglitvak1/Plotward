import io
from dataclasses import dataclass

import pillow_heif
from PIL import Image, ImageOps

pillow_heif.register_heif_opener()

# Pillow reports some camera JPEGs as MPO.
SUPPORTED_FORMATS = {"JPEG": ".jpg", "MPO": ".jpg", "HEIF": ".heic"}
MASTER_MAX_PX = 2048
THUMB_MAX_PX = 256


@dataclass(frozen=True)
class Derivatives:
    width: int
    height: int
    master: bytes
    thumbnail: bytes


def _jpeg(image: Image.Image, max_px: int, quality: int) -> bytes:
    copy = image.copy()
    copy.thumbnail((max_px, max_px), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    copy.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def make_derivatives(image: Image.Image) -> Derivatives:
    """Orientation-corrected master and thumbnail. Derivatives carry no EXIF."""
    upright = ImageOps.exif_transpose(image)
    return Derivatives(
        width=upright.width,
        height=upright.height,
        master=_jpeg(upright, MASTER_MAX_PX, 85),
        thumbnail=_jpeg(upright, THUMB_MAX_PX, 80),
    )
