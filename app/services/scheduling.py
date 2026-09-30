"""Interview availability slots and atomic booking (FP-SCHED-1..3).

All slot times are UTC. Slots are exactly 30 minutes. Booking runs inside a
``BEGIN IMMEDIATE`` transaction and is backstopped by the UNIQUE constraints on
``bookings.slot_id`` and ``bookings.application_id``, so two concurrent booking
attempts produce exactly one booking; the loser gets HTTP 409 with the message
``Slot already booked``.
"""

import sqlite3
from datetime import timedelta

from app.db import get_db, transaction, translate_integrity_error
from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.timeutils import SLOT_MINUTES, is_future, parse_iso, to_iso, utc_now

CONFLICT_BOOKED = "Slot already booked"


def _validate_slot_times(start_utc: str, end_utc: str) -> tuple[str, str]:
    try:
        start = parse_iso(start_utc)
        end = parse_iso(end_utc)
    except (ValueError, TypeError):
        raise ValidationError("Times must be ISO-8601 UTC, e.g. 2026-05-01T15:00:00Z")
    if end <= start:
        raise ValidationError("End time must be after start time")
    if end - start != timedelta(minutes=SLOT_MINUTES):
        raise ValidationError(f"Slots must be exactly {SLOT_MINUTES} minutes")
    return to_iso(start), to_iso(end)


def create_slot(employer_id: int, job_id: int, start_utc: str, end_utc: str) -> int:
    """Create one future 30-minute slot owned by the employer (FP-SCHED-1)."""
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise NotFoundError("Job not found")
    if job["employer_id"] != employer_id:
        raise AuthorizationError("You do not own this job posting")
    start, end = _validate_slot_times(start_utc, end_utc)
    if not is_future(start):
        raise ValidationError("Slots must be in the future")
    try:
        with transaction():
            cur = db.execute(
                "INSERT INTO interview_slots (job_id, employer_id, start_utc, end_utc, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (job_id, employer_id, start, end, to_iso(utc_now())),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError as exc:
        # FOREIGN KEY: the job vanished between the ownership check and insert.
        translate_integrity_error(exc, missing_message="Job not found")


def delete_slot(employer_id: int, slot_id: int) -> None:
    """Delete an unbooked slot. Booked slots cannot be deleted (FP-SCHED-1).

    The booked-check and the DELETE run inside one ``BEGIN IMMEDIATE``
    transaction; ``bookings.slot_id ON DELETE RESTRICT`` is the DB-level
    backstop so a racing booking can never be cascade-deleted.
    """
    db = get_db()
    slot = db.execute("SELECT * FROM interview_slots WHERE id = ?", (slot_id,)).fetchone()
    if slot is None:
        raise NotFoundError("Slot not found")
    if slot["employer_id"] != employer_id:
        raise AuthorizationError("You do not own this slot")
    try:
        with transaction(immediate=True):
            booked = db.execute("SELECT 1 FROM bookings WHERE slot_id = ?", (slot_id,)).fetchone()
            if booked is not None:
                raise ConflictError("Cannot delete a booked slot")
            db.execute("DELETE FROM interview_slots WHERE id = ?", (slot_id,))
    except sqlite3.IntegrityError as exc:
        raise ConflictError("Cannot delete a booked slot") from exc


def list_slots_for_employer(employer_id: int) -> list[dict]:
    """All slots owned by the employer, with booking state."""
    db = get_db()
    rows = db.execute(
        """
        SELECT s.id AS slot_id, s.job_id, s.start_utc, s.end_utc, j.title,
               b.id AS booking_id, b.application_id
        FROM interview_slots s
        JOIN jobs j ON j.id = s.job_id
        LEFT JOIN bookings b ON b.slot_id = s.id
        WHERE s.employer_id = ?
        ORDER BY s.start_utc, s.id
        """,
        (employer_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_available_slots(employer_id: int) -> list[dict]:
    """Future, unbooked slots for an employer. Booked slots are never listed (FP-SCHED-1)."""
    now = to_iso(utc_now())
    db = get_db()
    rows = db.execute(
        """
        SELECT s.id AS slot_id, s.job_id, s.start_utc, s.end_utc, j.title
        FROM interview_slots s
        JOIN jobs j ON j.id = s.job_id
        LEFT JOIN bookings b ON b.slot_id = s.id
        WHERE s.employer_id = ? AND b.id IS NULL AND s.start_utc > ?
        ORDER BY s.start_utc, s.id
        """,
        (employer_id, now),
    ).fetchall()
    return [dict(row) for row in rows]


def book_slot(candidate_id: int, application_id: int, slot_id: int) -> int:
    """Book a slot for the candidate's application atomically (FP-SCHED-2, FP-SCHED-3).

    Eligibility is exactly: the candidate owns the application; the slot belongs
    to the employer for that application; the application status is
    ``Interviewing``; the slot is in the future and not booked; and the
    application has no existing booking. Ineligible attempts change nothing.
    """
    with transaction(immediate=True) as db:
        application = db.execute(
            "SELECT * FROM applications WHERE id = ?", (application_id,)
        ).fetchone()
        if application is None:
            raise NotFoundError("Application not found")
        if application["candidate_id"] != candidate_id:
            raise AuthorizationError("You cannot book with another candidate's application")

        slot = db.execute("SELECT * FROM interview_slots WHERE id = ?", (slot_id,)).fetchone()
        if slot is None:
            raise NotFoundError("Slot not found")

        job = db.execute("SELECT * FROM jobs WHERE id = ?", (application["job_id"],)).fetchone()
        if job is None or slot["employer_id"] != job["employer_id"]:
            raise AuthorizationError("Slot does not belong to the employer for this application")

        if application["status"] != "Interviewing":
            raise ConflictError("Application is not in Interviewing status")

        if not is_future(slot["start_utc"]):
            raise ConflictError("Slot is in the past")

        if db.execute("SELECT 1 FROM bookings WHERE slot_id = ?", (slot_id,)).fetchone() is not None:
            raise ConflictError(CONFLICT_BOOKED)

        if db.execute(
            "SELECT 1 FROM bookings WHERE application_id = ?", (application_id,)
        ).fetchone() is not None:
            raise ConflictError("Application already has a booking")

        try:
            cur = db.execute(
                "INSERT INTO bookings (slot_id, application_id, created_at) VALUES (?, ?, ?)",
                (slot_id, application_id, to_iso(utc_now())),
            )
        except sqlite3.IntegrityError as exc:
            # UNIQUE(slot_id) / UNIQUE(application_id): a concurrent writer won
            # the race -> 409 "Slot already booked". FOREIGN KEY: the slot or
            # application vanished mid-booking -> 404, never a 500.
            translate_integrity_error(
                exc,
                conflict_message=CONFLICT_BOOKED,
                missing_message="Application or slot not found",
            )
        return cur.lastrowid
