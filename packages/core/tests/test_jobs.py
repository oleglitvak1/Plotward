from plotward_core.db import garden_session
from plotward_core.jobs import MAX_ATTEMPTS, claim_job, complete_job, fail_job
from plotward_core.models import Job
from sqlalchemy import text


def _queue(session_factory, garden_id, kind="embed_photo", **payload):
    with garden_session(session_factory, garden_id) as s:
        s.add(Job(kind=kind, payload=payload))


def _row(session_factory):
    with session_factory() as s:
        return s.execute(text("select status, attempts, last_error from job")).one()


def test_claim_returns_the_job_once_and_marks_it_running(session_factory, garden_id):
    _queue(session_factory, garden_id, photo_id="abc")
    job = claim_job(session_factory)
    assert (job.kind, job.payload, job.attempts, job.garden_id) == (
        "embed_photo",
        {"photo_id": "abc"},
        1,
        garden_id,
    )
    assert claim_job(session_factory) is None
    assert _row(session_factory).status == "running"


def test_claim_on_an_empty_queue_returns_none(session_factory):
    assert claim_job(session_factory) is None


def test_complete_marks_done_and_clears_the_error(session_factory, garden_id):
    _queue(session_factory, garden_id)
    job = claim_job(session_factory)
    complete_job(session_factory, job.id)
    assert _row(session_factory).status == "done"
    assert claim_job(session_factory) is None


def test_failure_is_retried_later_with_backoff(session_factory, garden_id):
    _queue(session_factory, garden_id)
    job = claim_job(session_factory)
    assert fail_job(session_factory, job, "boom") is True
    row = _row(session_factory)
    assert (row.status, row.attempts, row.last_error) == ("queued", 1, "boom")
    assert claim_job(session_factory) is None  # not due yet


def test_a_job_that_keeps_failing_is_eventually_given_up_on(session_factory, garden_id):
    _queue(session_factory, garden_id)
    for _ in range(MAX_ATTEMPTS):
        with session_factory() as s:  # skip the backoff wait
            s.execute(text("update job set run_after = now() - interval '1 second'"))
            s.commit()
        job = claim_job(session_factory)
        retried = fail_job(session_factory, job, "still broken")
    assert retried is False and _row(session_factory).status == "failed"
    assert claim_job(session_factory) is None


def test_permanent_failure_is_not_retried(session_factory, garden_id):
    _queue(session_factory, garden_id, kind="mystery")
    job = claim_job(session_factory)
    assert fail_job(session_factory, job, "unknown kind", permanent=True) is False
    assert _row(session_factory).status == "failed"


def test_a_job_stuck_running_is_reclaimed(session_factory, garden_id):
    _queue(session_factory, garden_id)
    claim_job(session_factory)  # worker dies here
    with session_factory() as s:
        s.execute(text("update job set locked_at = now() - interval '11 minutes'"))
        s.commit()
    again = claim_job(session_factory)
    assert again is not None and again.attempts == 2
