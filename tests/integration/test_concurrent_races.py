"""Integration: genuine multi-threaded races against one SQLite database file.

The spec-required unit tests cover booking-conflict *logic*; this suite goes
further and exercises FP-SCHED-3's database-atomicity claim with real concurrent
connections (each thread in its own app context, synchronized by a barrier).
"""

import sqlite3

import pytest

from app.errors import ConflictError, NotFoundError
from app.services import applications as applications_service
from app.services import auth as auth_service
from app.services import jobs as jobs_service
from app.services import scheduling as scheduling_service
from app.services.scheduling import CONFLICT_BOOKED


def _setup_interviewing_pair(ids):
    app_a = applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"])
    app_b = applications_service.apply_to_job(ids["users"]["bob"], ids["jobs"]["backend"])
    applications_service.set_status(ids["users"]["ana"], app_a, "Interviewing")
    applications_service.set_status(ids["users"]["ana"], app_b, "Interviewing")
    return app_a, app_b


def test_two_candidates_race_for_one_slot_exactly_one_wins(app, db, world, race_calls):
    ids = world()
    app_a, app_b = _setup_interviewing_pair(ids)
    slot_id = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-01T15:00:00Z", "2030-05-01T15:30:00Z"
    )

    results = race_calls(
        lambda: scheduling_service.book_slot(ids["users"]["alice"], app_a, slot_id),
        lambda: scheduling_service.book_slot(ids["users"]["bob"], app_b, slot_id),
    )

    winners = [r for r in results if isinstance(r, int)]
    losers = [r for r in results if isinstance(r, Exception)]
    assert len(winners) == 1, f"expected exactly one winner, got {results!r}"
    assert len(losers) == 1, f"expected exactly one loser, got {results!r}"
    loser = losers[0]
    assert isinstance(loser, ConflictError), f"loser should get 409, got {loser!r}"
    assert loser.message == CONFLICT_BOOKED  # documented message, FP-SCHED-3
    rows = db.execute("SELECT application_id FROM bookings WHERE slot_id = ?", (slot_id,)).fetchall()
    assert len(rows) == 1
    assert rows[0]["application_id"] in (app_a, app_b)


def test_sequential_second_booking_gets_documented_conflict(db, world):
    ids = world()
    app_a, app_b = _setup_interviewing_pair(ids)
    slot_id = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-01T15:00:00Z", "2030-05-01T15:30:00Z"
    )
    scheduling_service.book_slot(ids["users"]["alice"], app_a, slot_id)
    with pytest.raises(ConflictError) as excinfo:
        scheduling_service.book_slot(ids["users"]["bob"], app_b, slot_id)
    assert excinfo.value.message == CONFLICT_BOOKED
    assert db.execute("SELECT COUNT(*) AS n FROM bookings").fetchone()["n"] == 1


def test_same_candidate_racing_two_slots_for_one_application(app, db, world, race_calls):
    """UNIQUE(application_id) backstop: one application can hold at most one booking."""
    ids = world()
    app_a, _ = _setup_interviewing_pair(ids)
    slot1 = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-01T15:00:00Z", "2030-05-01T15:30:00Z"
    )
    slot2 = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-02T15:00:00Z", "2030-05-02T15:30:00Z"
    )
    results = race_calls(
        lambda: scheduling_service.book_slot(ids["users"]["alice"], app_a, slot1),
        lambda: scheduling_service.book_slot(ids["users"]["alice"], app_a, slot2),
    )
    winners = [r for r in results if isinstance(r, int)]
    assert len(winners) == 1, f"expected exactly one booking, got {results!r}"
    assert db.execute("SELECT COUNT(*) AS n FROM bookings").fetchone()["n"] == 1


def test_concurrent_duplicate_applications_cannot_create_two_rows(app, db, world, race_calls):
    ids = world()
    results = race_calls(
        lambda: applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"]),
        lambda: applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"]),
    )
    winners = [r for r in results if isinstance(r, int)]
    losers = [r for r in results if isinstance(r, ConflictError)]
    assert len(winners) == 1 and len(losers) == 1, f"got {results!r}"
    assert losers[0].message == "Application already submitted"
    assert db.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"] == 1


def test_concurrent_duplicate_registrations_cannot_create_two_users(app, db, race_calls):
    results = race_calls(
        lambda: auth_service.register_user("race@test.local", "Password123!", "Candidate", display_name="R1"),
        lambda: auth_service.register_user("race@test.local", "Password123!", "Candidate", display_name="R2"),
    )
    winners = [r for r in results if isinstance(r, int)]
    losers = [r for r in results if isinstance(r, ConflictError)]
    assert len(winners) == 1 and len(losers) == 1, f"got {results!r}"
    assert losers[0].message == "Email already registered"
    assert db.execute("SELECT COUNT(*) AS n FROM users WHERE email = 'race@test.local'").fetchone()["n"] == 1


def test_concurrent_apply_and_delete_job_agree_on_outcome(app, db, world, race_calls):
    """Whatever the interleaving, the job either survives with its application or is gone.

    The loser of the race must observe a clean 409 (delete) or 404 (apply), never
    a 500 and never a job with an orphaned application row.
    """
    ids = world()
    results = race_calls(
        lambda: jobs_service.delete_job(ids["users"]["ben"], ids["jobs"]["analyst"]),
        lambda: applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["analyst"]),
    )
    job_after = db.execute("SELECT 1 FROM jobs WHERE id = ?", (ids["jobs"]["analyst"],)).fetchone()
    apps_after = db.execute(
        "SELECT COUNT(*) AS n FROM applications WHERE job_id = ?", (ids["jobs"]["analyst"],)
    ).fetchone()["n"]

    delete_result, apply_result = results
    if isinstance(delete_result, Exception):
        assert isinstance(delete_result, ConflictError), f"delete should be 409, got {delete_result!r}"
        assert job_after is not None
        assert apps_after == 1
    else:
        assert isinstance(apply_result, Exception), "apply must fail once the job is deleted"
        assert isinstance(apply_result, (NotFoundError, ConflictError)), f"got {apply_result!r}"
        assert job_after is None
        assert apps_after == 0


def test_booking_race_loser_can_retry_on_another_slot(db, world):
    """System requirement: an ineligible booking attempt changes nothing (FP-SCHED-2)."""
    ids = world()
    app_a, app_b = _setup_interviewing_pair(ids)
    slot1 = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-01T15:00:00Z", "2030-05-01T15:30:00Z"
    )
    slot2 = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-02T15:00:00Z", "2030-05-02T15:30:00Z"
    )
    scheduling_service.book_slot(ids["users"]["alice"], app_a, slot1)
    with pytest.raises(ConflictError):
        scheduling_service.book_slot(ids["users"]["bob"], app_b, slot1)
    # Bob's failed attempt left no partial state; he can still book the spare slot.
    booking_id = scheduling_service.book_slot(ids["users"]["bob"], app_b, slot2)
    assert isinstance(booking_id, int)
    assert db.execute("SELECT COUNT(*) AS n FROM bookings").fetchone()["n"] == 2
