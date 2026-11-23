import hashlib
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..config import Settings
from ..models import Garden, Job, Photo
from .exif import parse_exif
from .images import SUPPORTED_FORMATS, make_derivatives
from .storage import PhotoStore

EMBED_JOB_KIND = "embed_photo"


class IngestError(Exception):
    pass


class UnsupportedImageError(IngestError):
    """Not a JPEG or HEIC image, or not decodable."""


@dataclass(frozen=True)
class IngestResult:
    photo: Photo
    duplicate: bool


def _point_wkt(lon: float, lat: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


def ingest_photo(session: Session, settings: Settings, data: bytes) -> IngestResult:
    """Store one photo and queue it for embedding. Idempotent on content hash.

    `session` must be garden-scoped (see scoping.garden_session). The caller commits.
    """
    garden_id = session.info["garden_id"]
    content_hash = hashlib.sha256(data).hexdigest()

    existing = session.scalars(select(Photo).where(Photo.content_hash == content_hash)).first()
    if existing is not None:
        return IngestResult(existing, duplicate=True)

    try:
        image = Image.open(io.BytesIO(data))
        image.load()
    except (UnidentifiedImageError, OSError, ValueError, SyntaxError) as exc:
        raise UnsupportedImageError("not a decodable image") from exc
    if image.format not in SUPPORTED_FORMATS:
        raise UnsupportedImageError(f"unsupported format {image.format}; send JPEG or HEIC")

    garden = session.get(Garden, garden_id)
    parsed = parse_exif(image, garden.timezone if garden else "UTC")
    derivatives = make_derivatives(image)

    store = PhotoStore(settings.data_dir)
    original_key = store.key(garden_id, content_hash, f"original{SUPPORTED_FORMATS[image.format]}")
    store.write(original_key, data)
    store.write(store.key(garden_id, content_hash, "master.jpg"), derivatives.master)
    store.write(store.key(garden_id, content_hash, "thumb.jpg"), derivatives.thumbnail)

    photo = Photo(
        garden_id=garden_id,
        captured_at=parsed.captured_at,
        exif=parsed.raw,
        gps=(
            _point_wkt(parsed.longitude, parsed.latitude)
            if parsed.latitude is not None and parsed.longitude is not None
            else None
        ),
        file_key=original_key,
        content_hash=content_hash,
        byte_size=len(data),
        width=derivatives.width,
        height=derivatives.height,
    )
    try:
        with session.begin_nested():
            session.add(photo)
            session.flush()
            session.add(
                Job(garden_id=garden_id, kind=EMBED_JOB_KIND, payload={"photo_id": str(photo.id)})
            )
    except IntegrityError:
        # A concurrent upload of the same bytes won the race; return that row.
        winner = session.scalars(select(Photo).where(Photo.content_hash == content_hash)).one()
        return IngestResult(winner, duplicate=True)
    return IngestResult(photo, duplicate=False)
