import logging

from plotward_core.config import get_settings
from plotward_core.db import make_session_factory
from plotward_core.models import EMBEDDING_DIM
from plotward_ml import create_embedder

from .runner import run_forever


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    settings = get_settings()
    embedder = create_embedder(
        settings.embedder, model=settings.open_clip_model, pretrained=settings.open_clip_pretrained
    )
    if embedder.dim != EMBEDDING_DIM:
        raise SystemExit(
            f"{embedder.name} produces {embedder.dim}-d vectors but the schema holds "
            f"{EMBEDDING_DIM}. Change the model or add a migration."
        )
    run_forever(make_session_factory(), settings, embedder)


if __name__ == "__main__":
    main()
