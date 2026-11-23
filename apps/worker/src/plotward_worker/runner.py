import logging
import signal
import threading

from plotward_core.config import Settings
from plotward_core.jobs import claim_job, complete_job, fail_job
from plotward_ml import Embedder
from sqlalchemy.orm import Session, sessionmaker

from .handlers import HANDLERS, PermanentJobError

log = logging.getLogger("plotward.worker")


def run_once(factory: sessionmaker[Session], settings: Settings, embedder: Embedder) -> bool:
    """Claim and process one job. Returns False when the queue is empty."""
    job = claim_job(factory)
    if job is None:
        return False
    handler = HANDLERS.get(job.kind)
    if handler is None:
        fail_job(factory, job, f"unknown job kind {job.kind!r}", permanent=True)
        log.error("job %s: unknown kind %r", job.id, job.kind)
        return True
    try:
        handler(factory, settings, embedder, job)
    except PermanentJobError as exc:
        fail_job(factory, job, str(exc), permanent=True)
        log.error("job %s failed permanently: %s", job.id, exc)
    except Exception as exc:
        will_retry = fail_job(factory, job, f"{type(exc).__name__}: {exc}")
        log.exception("job %s failed (%s)", job.id, "will retry" if will_retry else "giving up")
    else:
        complete_job(factory, job.id)
        log.info("job %s (%s) done", job.id, job.kind)
    return True


def run_forever(
    factory: sessionmaker[Session],
    settings: Settings,
    embedder: Embedder,
    *,
    poll_seconds: float = 2.0,
    stop: threading.Event | None = None,
) -> None:
    stop = stop or threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    log.info("worker started (embedder %s %s)", embedder.name, embedder.version)
    while not stop.is_set():
        if not run_once(factory, settings, embedder):
            stop.wait(poll_seconds)
    log.info("worker stopped")
