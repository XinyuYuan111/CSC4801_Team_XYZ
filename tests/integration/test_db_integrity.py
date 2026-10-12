"""Integration: real SQLite schema constraints the services rely on as backstops.

These tests talk to the actual ``app/db.py`` schema through raw SQL (no service
layer) to prove that the database itself — not just application code — enforces
the uniqueness / CHECK / ON DELETE RESTRICT guarantees claimed in SPEC.md.
"""

import sqlite3

import pytest

from app.errors import AuthorizationError, ConflictError
from app.services import applications as applications_service
from app.services import jobs as jobs_service
from app.services import scheduling as scheduling_service


def test_unique_application_constraint_rejects_duplicate_rows(db, world):
    ids = world()
    db.execute(
        "INSERT INTO applications (job_id, candidate_id, status, created_at)"
        " VALUES (?, ?, 'Pending', '2026-01-01T00:00:00Z')",
        (ids["jobs"]["backend"], ids["users"]["alice"]),
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO applications (job_id, candidate_id, status, created_at)"
            " VALUES (?, ?, 'Pending', '2026-01-01T00:00:00Z')",
            (ids["jobs"]["backend"], ids["users"]["alice"]),
        )


def test_application_status_check_rejects_unknown_status(db, world):
    ids = world()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO applications (job_id, candidate_id, status, created_at)"
            " VALUES (?, ?, 'Hired', '2026-01-01T00:00:00Z')",
            (ids["jobs"]["backend"], ids["users"]["alice"]),
        )


def test_user_role_check_rejects_unknown_role(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO users (email, password_hash, role, created_at)"
            " VALUES ('x@test.local', 'hash', 'Admin', '2026-01-01T00:00:00Z')",
        )


def test_slot_check_rejects_end_before_start(db, world):
    ids = world()
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO interview_slots (job_id, employer_id, start_utc, end_utc, created_at)"
            " VALUES (?, ?, '2026-05-01T15:00:00Z', '2026-05-01T14:00:00Z', '2026-01-01T00:00:00Z')",
            (ids["jobs"]["backend"], ids["users"]["ana"]),
        )


def test_booking_uniqueness_constraints(db, world):
    """One booking per slot AND one booking per application, at the DB level."""
    ids = world(include_cara=True)
    app1 = applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"])
    applications_service.set_status(ids["users"]["ana"], app1, "Interviewing")
    slot1 = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-01T15:00:00Z", "2030-05-01T15:30:00Z"
    )
    slot2 = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-02T15:00:00Z", "2030-05-02T15:30:00Z"
    )
    db.execute(
        "INSERT INTO bookings (slot_id, application_id, created_at) VALUES (?, ?, '2026-01-01T00:00:00Z')",
        (slot1, app1),
    )
    # Same slot, second application -> UNIQUE(slot_id).
    app2 = applications_service.apply_to_job(ids["users"]["cara"], ids["jobs"]["backend"])
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO bookings (slot_id, application_id, created_at) VALUES (?, ?, '2026-01-01T00:00:00Z')",
            (slot1, app2),
        )
    # Same application, second slot -> UNIQUE(application_id).
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO bookings (slot_id, application_id, created_at) VALUES (?, ?, '2026-01-01T00:00:00Z')",
            (slot2, app1),
        )


def test_job_delete_restrict_is_database_backstop(db, world):
    """Even a raw DELETE cannot destroy a job that has applications (ON DELETE RESTRICT)."""
    ids = world()
    applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"])
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM jobs WHERE id = ?", (ids["jobs"]["backend"],))
    # Service layer maps the same situation to 409 and leaves the job intact.
    with pytest.raises(ConflictError):
        jobs_service.delete_job(ids["users"]["ana"], ids["jobs"]["backend"])
    assert db.execute("SELECT 1 FROM jobs WHERE id = ?", (ids["jobs"]["backend"],)).fetchone()
    assert db.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"] == 1


def test_booked_slot_delete_restrict_is_database_backstop(db, world):
    ids = world()
    app_id = applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"])
    applications_service.set_status(ids["users"]["ana"], app_id, "Interviewing")
    slot_id = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-01T15:00:00Z", "2030-05-01T15:30:00Z"
    )
    scheduling_service.book_slot(ids["users"]["alice"], app_id, slot_id)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM interview_slots WHERE id = ?", (slot_id,))
    with pytest.raises(ConflictError):
        scheduling_service.delete_slot(ids["users"]["ana"], slot_id)
    assert db.execute("SELECT 1 FROM bookings WHERE slot_id = ?", (slot_id,)).fetchone()


def test_job_with_slots_but_no_applications_cannot_be_deleted(db, world):
    """FP-EMP-2: either dependent kind blocks deletion with 409, job unchanged."""
    ids = world()
    scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-01T15:00:00Z", "2030-05-01T15:30:00Z"
    )
    with pytest.raises(ConflictError):
        jobs_service.delete_job(ids["users"]["ana"], ids["jobs"]["backend"])
    assert db.execute("SELECT 1 FROM jobs WHERE id = ?", (ids["jobs"]["backend"],)).fetchone()
    assert db.execute("SELECT COUNT(*) AS n FROM interview_slots").fetchone()["n"] == 1


def test_employer_cannot_delete_foreign_job_even_at_service_layer(app, world):
    ids = world()
    with app.app_context(), pytest.raises(AuthorizationError):
        jobs_service.delete_job(ids["users"]["ben"], ids["jobs"]["backend"])
