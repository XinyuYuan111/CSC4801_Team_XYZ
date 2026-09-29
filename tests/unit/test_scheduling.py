"""Unit tests for FP-SCHED-1..3: availability slots, booking eligibility, conflict contract."""

import sqlite3
from datetime import timedelta

import pytest

from app.db import get_db, transaction
from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.services import applications as applications_service
from app.services import scheduling as scheduling_service
from app.timeutils import plus_minutes, to_iso, utc_now
from tests.conftest import make_future_slot_start, make_slot_end


def _interview_app(app, ids, candidate_key: str, job_key: str) -> int:
    """Create an application and move it to Interviewing (job owner sets status)."""
    with app.app_context():
        app_id = applications_service.apply_to_job(ids["users"][candidate_key], ids["jobs"][job_key])
        ids["applications"][f"{candidate_key}_{job_key}"] = app_id
        owner = ids["users"]["ana"] if job_key == "backend" else ids["users"]["ben"]
        applications_service.set_status(owner, app_id, "Interviewing")
    return app_id


def _past_slot(app, job_id: int, employer_id: int) -> int:
    """Insert a past slot directly (creation rejects past slots; booking must too)."""
    with app.app_context():
        start = to_iso(utc_now().replace(microsecond=0) - timedelta(days=1))
        with transaction():
            cur = get_db().execute(
                "INSERT INTO interview_slots (job_id, employer_id, start_utc, end_utc, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (job_id, employer_id, start, plus_minutes(start, 30), to_iso(utc_now())),
            )
    return cur.lastrowid


def test_fp_sched_1_slot_creation_timezones_and_deletion(app, world):
    ids = world()
    ana = ids["users"]["ana"]
    backend = ids["jobs"]["backend"]
    start = make_future_slot_start()
    end = make_slot_end(start)

    with app.app_context():
        slot_id = scheduling_service.create_slot(ana, backend, start, end)

        # Exact start/end stored; the documented timezone is UTC (ISO-8601 Z).
        slots = scheduling_service.list_slots_for_employer(ana)
        slot = next(s for s in slots if s["slot_id"] == slot_id)
        assert slot["start_utc"] == start
        assert slot["end_utc"] == end
        assert start.endswith("Z") and end.endswith("Z")
        assert slot["booking_id"] is None

        # Available listing shows the unbooked future slot.
        available = scheduling_service.list_available_slots(ana)
        assert any(s["slot_id"] == slot_id for s in available)

        # An unbooked slot can be deleted and disappears.
        scheduling_service.delete_slot(ana, slot_id)
        assert all(s["slot_id"] != slot_id for s in scheduling_service.list_slots_for_employer(ana))
        assert all(s["slot_id"] != slot_id for s in scheduling_service.list_available_slots(ana))

        # Ownership: Ben cannot create a slot on Ana's job (403).
        with pytest.raises(AuthorizationError):
            scheduling_service.create_slot(ids["users"]["ben"], backend, start, end)

        # Missing job: 404.
        with pytest.raises(NotFoundError):
            scheduling_service.create_slot(ana, 99999, start, end)

        # Deleting a missing slot: 404. Deleting another employer's slot: 403.
        other_id = scheduling_service.create_slot(ana, backend, start, end)
        with pytest.raises(NotFoundError):
            scheduling_service.delete_slot(ana, 99999)
        with pytest.raises(AuthorizationError):
            scheduling_service.delete_slot(ids["users"]["ben"], other_id)


def test_fp_sched_1_invalid_slots(app, world):
    ids = world()
    ana = ids["users"]["ana"]
    backend = ids["jobs"]["backend"]
    start = make_future_slot_start()

    with app.app_context():
        # Wrong duration (25 minutes).
        with pytest.raises(ValidationError):
            scheduling_service.create_slot(ana, backend, start, plus_minutes(start, 25))
        # Wrong duration (45 minutes).
        with pytest.raises(ValidationError):
            scheduling_service.create_slot(ana, backend, start, plus_minutes(start, 45))
        # End before start.
        with pytest.raises(ValidationError):
            scheduling_service.create_slot(ana, backend, start, plus_minutes(start, -30))
        # Zero-length slot.
        with pytest.raises(ValidationError):
            scheduling_service.create_slot(ana, backend, start, start)
        # Past slot.
        past = to_iso(utc_now().replace(microsecond=0) - timedelta(hours=1))
        with pytest.raises(ValidationError):
            scheduling_service.create_slot(ana, backend, past, plus_minutes(past, 30))
        # Garbage timestamps.
        with pytest.raises(ValidationError):
            scheduling_service.create_slot(ana, backend, "not-a-time", "also-not-a-time")

        # Deletion of a booked slot is rejected and the slot remains.
        app_id = _interview_app(app, ids, "alice", "backend")
        slot_id = scheduling_service.create_slot(ana, backend, start, make_slot_end(start))
        scheduling_service.book_slot(ids["users"]["alice"], app_id, slot_id)
        with pytest.raises(ConflictError):
            scheduling_service.delete_slot(ana, slot_id)
        assert any(s["slot_id"] == slot_id for s in scheduling_service.list_slots_for_employer(ana))
        # Booked slots are never shown as available.
        assert all(s["slot_id"] != slot_id for s in scheduling_service.list_available_slots(ana))

        # DB-level backstop: ON DELETE RESTRICT refuses the raw delete of a
        # booked slot, so the booking can never be cascade-removed (P6).
        with pytest.raises(sqlite3.IntegrityError):
            with transaction():
                get_db().execute("DELETE FROM interview_slots WHERE id = ?", (slot_id,))
        assert get_db().execute(
            "SELECT COUNT(*) AS n FROM bookings WHERE slot_id = ?", (slot_id,)
        ).fetchone()["n"] == 1


def test_fp_sched_2_eligible_booking(app, world):
    ids = world()
    ana = ids["users"]["ana"]
    alice = ids["users"]["alice"]
    app_id = _interview_app(app, ids, "alice", "backend")
    start = make_future_slot_start()

    with app.app_context():
        slot_id = scheduling_service.create_slot(
            ana, ids["jobs"]["backend"], start, make_slot_end(start)
        )
        booking_id = scheduling_service.book_slot(alice, app_id, slot_id)
        assert booking_id is not None

        # Booking is linked to the application and visible to the candidate.
        detail = applications_service.get_application_for_candidate(alice, app_id)
        assert detail["booking"] is not None
        assert detail["booking"]["slot_id"] == slot_id
        assert detail["booking"]["start_utc"] == start

        # ...and to the owning employer.
        applicants = applications_service.list_applicants(ana, ids["jobs"]["backend"])
        row = next(a for a in applicants if a["application_id"] == app_id)
        assert row["booking"] is not None
        assert row["booking"]["slot_id"] == slot_id

        # The slot is no longer available.
        assert all(s["slot_id"] != slot_id for s in scheduling_service.list_available_slots(ana))


def test_fp_sched_2_ineligible_booking(app, world):
    ids = world(include_cara=True)
    ana, ben = ids["users"]["ana"], ids["users"]["ben"]
    alice, bob, cara = ids["users"]["alice"], ids["users"]["bob"], ids["users"]["cara"]
    backend, analyst = ids["jobs"]["backend"], ids["jobs"]["analyst"]
    start = make_future_slot_start()

    with app.app_context():
        slot_id = scheduling_service.create_slot(ana, backend, start, make_slot_end(start))
        other_slot = scheduling_service.create_slot(ben, analyst, start, make_slot_end(start))
        past_slot = _past_slot(app, backend, ana)

        # The candidate does not own the application -> 403.
        alice_app = applications_service.apply_to_job(alice, backend)
        with pytest.raises(AuthorizationError):
            scheduling_service.book_slot(bob, alice_app, slot_id)

        # The slot does not belong to the employer for the application -> ineligible.
        applications_service.set_status(ana, alice_app, "Interviewing")
        with pytest.raises(AuthorizationError):
            scheduling_service.book_slot(alice, alice_app, other_slot)

        # The application status is not Interviewing -> ineligible.
        cara_app = applications_service.apply_to_job(cara, backend)
        with pytest.raises(ConflictError):
            scheduling_service.book_slot(cara, cara_app, slot_id)  # Pending

        # The slot is in the past -> ineligible.
        bob_app = applications_service.apply_to_job(bob, backend)
        applications_service.set_status(ana, bob_app, "Interviewing")
        with pytest.raises(ConflictError):
            scheduling_service.book_slot(bob, bob_app, past_slot)

        # The application already has a booking -> ineligible.
        assert scheduling_service.book_slot(alice, alice_app, slot_id) is not None
        spare_start = make_future_slot_start()
        spare = scheduling_service.create_slot(
            ana, backend, plus_minutes(spare_start, 60), plus_minutes(spare_start, 90)
        )
        with pytest.raises(ConflictError):
            scheduling_service.book_slot(alice, alice_app, spare)

        # Missing application / missing slot -> 404.
        with pytest.raises(NotFoundError):
            scheduling_service.book_slot(alice, 99999, spare)
        with pytest.raises(NotFoundError):
            scheduling_service.book_slot(bob, bob_app, 99999)

        # All ineligible attempts left exactly one booking in the database.
        count = get_db().execute("SELECT COUNT(*) AS n FROM bookings").fetchone()["n"]
        assert count == 1


def test_fp_sched_2_booking_survives_status_change(app, world):
    ids = world()
    ana, alice = ids["users"]["ana"], ids["users"]["alice"]
    app_id = _interview_app(app, ids, "alice", "backend")
    start = make_future_slot_start()

    with app.app_context():
        slot_id = scheduling_service.create_slot(
            ana, ids["jobs"]["backend"], start, make_slot_end(start)
        )
        scheduling_service.book_slot(alice, app_id, slot_id)

        # Application leaves Interviewing: booking stays linked, slot stays unavailable.
        applications_service.set_status(ana, app_id, "Rejected")
        detail = applications_service.get_application_for_candidate(alice, app_id)
        assert detail["status"] == "Rejected"
        assert detail["booking"] is not None
        assert detail["booking"]["slot_id"] == slot_id
        assert all(s["slot_id"] != slot_id for s in scheduling_service.list_available_slots(ana))
        booked = get_db().execute(
            "SELECT COUNT(*) AS n FROM bookings WHERE slot_id = ?", (slot_id,)
        ).fetchone()["n"]
        assert booked == 1


def test_fp_sched_3_conflict_contract(app, world):
    ids = world()
    ana, alice, bob = ids["users"]["ana"], ids["users"]["alice"], ids["users"]["bob"]
    alice_app = _interview_app(app, ids, "alice", "backend")
    bob_app = _interview_app(app, ids, "bob", "backend")
    start = make_future_slot_start()

    with app.app_context():
        slot_id = scheduling_service.create_slot(
            ana, ids["jobs"]["backend"], start, make_slot_end(start)
        )

        # Two eligible candidates race for the same slot: exactly one succeeds,
        # the loser gets HTTP 409 with the exact message "Slot already booked".
        first = scheduling_service.book_slot(alice, alice_app, slot_id)
        assert first is not None
        with pytest.raises(ConflictError) as excinfo:
            scheduling_service.book_slot(bob, bob_app, slot_id)
        assert excinfo.value.status == 409
        assert excinfo.value.message == "Slot already booked"

        # The database holds exactly one booking for the slot afterward.
        count = get_db().execute(
            "SELECT COUNT(*) AS n FROM bookings WHERE slot_id = ?", (slot_id,)
        ).fetchone()["n"]
        assert count == 1

        # Database-level atomicity backstop: the UNIQUE constraint rejects a
        # second booking row for the same slot even if checks were bypassed.
        with pytest.raises(sqlite3.IntegrityError):
            with transaction():
                get_db().execute(
                    "INSERT INTO bookings (slot_id, application_id, created_at) VALUES (?, ?, ?)",
                    (slot_id, bob_app, "2026-01-01T00:00:00Z"),
                )


def test_fp_sched_3_http_conflict_status_and_message(client, app, world):
    """The booking race loser observes HTTP 409 and the exact contract message."""
    ids = world()
    ana, alice, bob = ids["users"]["ana"], ids["users"]["alice"], ids["users"]["bob"]
    alice_app = _interview_app(app, ids, "alice", "backend")
    bob_app = _interview_app(app, ids, "bob", "backend")
    start = make_future_slot_start()

    with app.app_context():
        slot_id = scheduling_service.create_slot(
            ana, ids["jobs"]["backend"], start, make_slot_end(start)
        )

    client.login("alice@test.local", "Password123!")
    response = client.post("/bookings", data={"application_id": alice_app, "slot_id": slot_id})
    assert response.status_code == 302

    client.logout()
    client.login("bob@test.local", "Password123!")
    response = client.post("/bookings", data={"application_id": bob_app, "slot_id": slot_id})
    assert response.status_code == 409
    assert b"Slot already booked" in response.data
