"""SQLite database access layer.

All user-controlled values are passed as bound parameters (FP-SEC-2): no SQL
string is ever built by concatenating user input. Skill lists are stored in
dedicated tables so the matching function reads normalized rows.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

SCHEMA = """
PRAGMA foreign_keys = ON;

-- Dependent rows use ON DELETE RESTRICT (never CASCADE) so a raced or buggy
-- delete can never silently destroy applications, slots, or bookings; the
-- service layer reports 409 instead (FP-EMP-2, FP-SCHED-1..2).

CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role          TEXT NOT NULL CHECK (role IN ('Candidate', 'Employer')),
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS candidate_profiles (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    display_name TEXT NOT NULL,
    resume_text  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS candidate_skills (
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    skill   TEXT NOT NULL,
    PRIMARY KEY (user_id, skill)
);

CREATE TABLE IF NOT EXISTS company_profiles (
    user_id      INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    company_name TEXT NOT NULL,
    description  TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    employer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS job_skills (
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    skill  TEXT NOT NULL,
    PRIMARY KEY (job_id, skill)
);

CREATE TABLE IF NOT EXISTS applications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id       INTEGER NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    candidate_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    status       TEXT NOT NULL DEFAULT 'Pending'
                 CHECK (status IN ('Pending', 'Interviewing', 'Rejected', 'Accepted')),
    created_at   TEXT NOT NULL,
    UNIQUE (job_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS interview_slots (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER NOT NULL REFERENCES jobs(id) ON DELETE RESTRICT,
    employer_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    start_utc   TEXT NOT NULL,
    end_utc     TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    CHECK (end_utc > start_utc)
);

CREATE TABLE IF NOT EXISTS bookings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id        INTEGER NOT NULL UNIQUE REFERENCES interview_slots(id) ON DELETE RESTRICT,
    application_id INTEGER NOT NULL UNIQUE REFERENCES applications(id) ON DELETE RESTRICT,
    created_at     TEXT NOT NULL
);
"""


def get_db() -> sqlite3.Connection:
    """Return the per-request SQLite connection (dict-like rows, autocommit)."""
    if "db" not in g:
        db = sqlite3.connect(
            current_app.config["DATABASE"],
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        db.row_factory = sqlite3.Row
        # Autocommit mode: transactions are opened explicitly (see transaction()).
        db.isolation_level = None
        db.execute("PRAGMA foreign_keys = ON")
        g.db = db
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transaction(immediate: bool = False):
    """Run a write transaction.

    ``immediate=True`` issues ``BEGIN IMMEDIATE``, taking the database write
    lock up front. Booking uses this so two concurrent booking attempts are
    serialized by SQLite; the UNIQUE constraints on bookings are the final
    backstop (FP-SCHED-3).
    """
    db = get_db()
    db.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield db
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise


def init_db():
    """Create all tables. Idempotent: safe to run on every start."""
    db = get_db()
    db.executescript(SCHEMA)


def reset_db():
    """Drop every application table and recreate the schema (demo reset)."""
    db = get_db()
    tables = [
        "bookings",
        "interview_slots",
        "applications",
        "job_skills",
        "jobs",
        "candidate_skills",
        "company_profiles",
        "candidate_profiles",
        "users",
    ]
    db.execute("BEGIN")
    try:
        for table in tables:
            db.execute(f"DROP TABLE IF EXISTS {table}")
        db.execute("COMMIT")
    except Exception:
        db.execute("ROLLBACK")
        raise
    init_db()


def init_app(app):
    app.teardown_appcontext(close_db)
    path = Path(app.config["DATABASE"])
    if path.parent and str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)
