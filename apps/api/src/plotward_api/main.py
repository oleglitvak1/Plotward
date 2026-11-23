import hmac
import uuid
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from geoalchemy2 import Geometry
from plotward_core.config import Settings, get_settings
from plotward_core.db import ensure_default_garden, garden_session, make_session_factory
from plotward_core.ingest import UnsupportedImageError, ingest_photo
from plotward_core.models import Photo
from pydantic import BaseModel
from sqlalchemy import cast, func, select, text
from sqlalchemy.orm import Session, sessionmaker


class PhotoOut(BaseModel):
    id: uuid.UUID
    content_hash: str
    captured_at: datetime | None
    received_at: datetime
    latitude: float | None
    longitude: float | None
    width: int
    height: int
    byte_size: int
    duplicate: bool = False


def _photo_out(session: Session, photo: Photo, duplicate: bool = False) -> PhotoOut:
    lat = lon = None
    if photo.gps is not None:
        point = cast(Photo.gps, Geometry)
        lat, lon = session.execute(
            select(func.ST_Y(point), func.ST_X(point)).where(Photo.id == photo.id)
        ).one()
    return PhotoOut(
        id=photo.id,
        content_hash=photo.content_hash,
        captured_at=photo.captured_at,
        received_at=photo.received_at,
        latitude=lat,
        longitude=lon,
        width=photo.width,
        height=photo.height,
        byte_size=photo.byte_size,
        duplicate=duplicate,
    )


def create_app(
    settings: Settings | None = None, session_factory: sessionmaker[Session] | None = None
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not settings.api_key:
            raise RuntimeError("PLOTWARD_API_KEY must be set")
        factory = session_factory or make_session_factory()
        app.state.session_factory = factory
        app.state.garden_id = ensure_default_garden(factory, settings)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        yield

    app = FastAPI(title="Plotward", lifespan=lifespan)

    def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
        if not x_api_key or not hmac.compare_digest(x_api_key, settings.api_key):
            raise HTTPException(status_code=401, detail="invalid or missing API key")

    def db(request: Request) -> Iterator[Session]:
        with garden_session(request.app.state.session_factory, request.app.state.garden_id) as s:
            yield s

    @app.get("/healthz")
    def healthz(request: Request) -> dict[str, str]:
        with request.app.state.session_factory() as session:
            session.execute(text("select 1"))
        return {"status": "ok"}

    @app.post("/photos", response_model=PhotoOut, dependencies=[Depends(require_key)])
    def upload_photo(
        response: Response,
        file: Annotated[UploadFile, File()],
        session: Annotated[Session, Depends(db)],
    ) -> PhotoOut:
        data = file.file.read(settings.max_upload_bytes + 1)
        if len(data) > settings.max_upload_bytes:
            raise HTTPException(
                status_code=413, detail=f"file larger than {settings.max_upload_mb} MB"
            )
        if not data:
            raise HTTPException(status_code=400, detail="empty file")
        try:
            result = ingest_photo(session, settings, data)
        except UnsupportedImageError as exc:
            raise HTTPException(status_code=415, detail=str(exc)) from exc
        session.flush()
        response.status_code = 200 if result.duplicate else 201
        return _photo_out(session, result.photo, result.duplicate)

    @app.get("/photos/{photo_id}", response_model=PhotoOut, dependencies=[Depends(require_key)])
    def get_photo(photo_id: uuid.UUID, session: Annotated[Session, Depends(db)]) -> PhotoOut:
        photo = session.scalars(select(Photo).where(Photo.id == photo_id)).first()
        if photo is None:
            raise HTTPException(status_code=404, detail="photo not found")
        return _photo_out(session, photo)

    return app


def app_factory() -> FastAPI:
    return create_app()
