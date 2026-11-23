"""The Postgres job queue.

Claiming a job is the one operation that must look across gardens (a worker serves every
garden), so it uses raw SQL, which the garden-scoping guard does not intercept. Everything the
worker does *with* a job then runs in a garden-scoped session.
"""

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

MAX_ATTEMPTS = 5
STUCK_AFTER = "10 minutes"  # a 'running' job older than this is assumed to belong to a dead worker

_CLAIM = text(
    f"""
    update job set status = 'running', locked_at = now(), attempts = attempts + 1
    where id = (
        select id from job
        where (status = 'queued' and run_after <= now())
           or (status = 'running' and locked_at < now() - interval '{STUCK_AFTER}')
        order by run_after, created_at
        for update skip locked
        limit 1
    )
    returning id, garden_id, kind, payload, attempts
    """
)


@dataclass(frozen=True)
class ClaimedJob:
    id: uuid.UUID
    garden_id: uuid.UUID
    kind: str
    payload: dict[str, Any]
    attempts: int


def claim_job(factory: sessionmaker[Session]) -> ClaimedJob | None:
    with factory() as session:
        row = session.execute(_CLAIM).mappings().first()
        session.commit()
    return ClaimedJob(**row) if row else None


def complete_job(factory: sessionmaker[Session], job_id: uuid.UUID) -> None:
    with factory() as session:
        session.execute(
            text(
                "update job set status = 'done', locked_at = null, last_error = null where id = :id"
            ),
            {"id": job_id},
        )
        session.commit()


def fail_job(
    factory: sessionmaker[Session], job: ClaimedJob, error: str, *, permanent: bool = False
) -> bool:
    """Record a failure. Retries with exponential backoff until MAX_ATTEMPTS. Returns True if the
    job will be retried."""
    retry = not permanent and job.attempts < MAX_ATTEMPTS
    with factory() as session:
        session.execute(
            text(
                """
                update job set status = :status, locked_at = null, last_error = :error,
                    run_after = now() + make_interval(secs => :delay)
                where id = :id
                """
            ),
            {
                "id": job.id,
                "status": "queued" if retry else "failed",
                "error": error[:2000],
                "delay": 30 * 2**job.attempts if retry else 0,
            },
        )
        session.commit()
    return retry
