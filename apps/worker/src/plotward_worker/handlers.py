import uuid
from pathlib import Path

from plotward_core.config import Settings
from plotward_core.db import garden_session
from plotward_core.ingest.storage import PhotoStore
from plotward_core.jobs import ClaimedJob
from plotward_core.matching import match_photo
from plotward_core.models import EMBEDDING_DIM, Photo
from plotward_ml import Embedder
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker


class PermanentJobError(Exception):
    """The job can never succeed; do not retry it."""


def handle_embed_photo(
    factory: sessionmaker[Session], settings: Settings, embedder: Embedder, job: ClaimedJob
) -> None:
    """Embed one photo, then match it to a plant. Safe to run twice: a photo that already has a
    current embedding is not re-embedded, and one that already has a plant is not re-matched."""
    try:
        photo_id = uuid.UUID(job.payload["photo_id"])
    except (KeyError, ValueError) as exc:
        raise PermanentJobError("job has no valid photo_id") from exc

    with garden_session(factory, job.garden_id) as session:
        photo = session.scalars(select(Photo).where(Photo.id == photo_id)).first()
        if photo is None:
            raise PermanentJobError(f"photo {photo_id} not found")

        current = photo.embedding is not None and (
            (photo.embedding_model, photo.embedding_version) == (embedder.name, embedder.version)
        )
        if not current:
            master = str(Path(photo.file_key).with_name("master.jpg"))
            vector = embedder.embed(PhotoStore(settings.data_dir).read(master))
            if len(vector) != EMBEDDING_DIM:
                raise PermanentJobError(
                    f"embedder returned {len(vector)} dims; the schema holds {EMBEDDING_DIM}"
                )
            photo.embedding = vector
            photo.embedding_model, photo.embedding_version = embedder.name, embedder.version

        if photo.plant_id is None:
            match_photo(session, settings, photo)


HANDLERS = {"embed_photo": handle_embed_photo}
