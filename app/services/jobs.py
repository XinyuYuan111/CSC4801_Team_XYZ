"""Job postings: CRUD, ownership rules, and deletion conflicts (FP-EMP-2, FP-CAN-2)."""

import sqlite3

from app.db import get_db, transaction
from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.matching import match_score, parse_skills_text, sort_jobs_for_candidate
from app.timeutils import utc_now_iso

DELETE_CONFLICT = "Job has applications or interview slots and cannot be deleted"


def _job_skills(db, job_id: int) -> list[str]:
    return [
        r["skill"]
        for r in db.execute("SELECT skill FROM job_skills WHERE job_id = ? ORDER BY skill", (job_id,))
    ]


def _load_job(db, job_id: int):
    return db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def create_job(employer_id: int, title: str, description: str, skills_text: str) -> int:
    title = (title or "").strip()
    description = (description or "").strip()
    if not title:
        raise ValidationError("Job title is required")
    if not description:
        raise ValidationError("Job description is required")
    skills = parse_skills_text(skills_text or "")  # empty list is allowed
    db = get_db()
    with transaction():
        cur = db.execute(
            "INSERT INTO jobs (employer_id, title, description, created_at) VALUES (?, ?, ?, ?)",
            (employer_id, title, description, utc_now_iso()),
        )
        job_id = cur.lastrowid
        db.executemany(
            "INSERT INTO job_skills (job_id, skill) VALUES (?, ?)",
            [(job_id, skill) for skill in skills],
        )
    return job_id


def update_job(actor_id: int, job_id: int, title: str, description: str, skills_text: str) -> dict:
    job = get_owned_job(actor_id, job_id)
    title = (title or "").strip()
    description = (description or "").strip()
    if not title:
        raise ValidationError("Job title is required")
    if not description:
        raise ValidationError("Job description is required")
    skills = parse_skills_text(skills_text or "")
    db = get_db()
    with transaction():
        db.execute(
            "UPDATE jobs SET title = ?, description = ? WHERE id = ?",
            (title, description, job["id"]),
        )
        db.execute("DELETE FROM job_skills WHERE job_id = ?", (job["id"],))
        db.executemany(
            "INSERT INTO job_skills (job_id, skill) VALUES (?, ?)",
            [(job["id"], skill) for skill in skills],
        )
    return get_job(job["id"])


def delete_job(actor_id: int, job_id: int) -> None:
    """Delete a job with no applications and no interview slots (FP-EMP-2).

    The dependent-record check and the DELETE run inside one
    ``BEGIN IMMEDIATE`` transaction so a concurrent apply/create_slot cannot
    slip a dependent row into the gap. Either dependent blocks deletion with
    409 Conflict and leaves the job and its dependents unchanged. The
    ``ON DELETE RESTRICT`` foreign keys are the database-level backstop.
    """
    get_owned_job(actor_id, job_id)
    db = get_db()
    try:
        with transaction(immediate=True):
            applications = db.execute(
                "SELECT COUNT(*) AS n FROM applications WHERE job_id = ?", (job_id,)
            ).fetchone()["n"]
            slots = db.execute(
                "SELECT COUNT(*) AS n FROM interview_slots WHERE job_id = ?", (job_id,)
            ).fetchone()["n"]
            if applications or slots:
                raise ConflictError(DELETE_CONFLICT)
            db.execute("DELETE FROM job_skills WHERE job_id = ?", (job_id,))
            db.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    except sqlite3.IntegrityError as exc:
        # RESTRICT backstop: a dependent row appeared in the same window.
        raise ConflictError(DELETE_CONFLICT) from exc


def get_job(job_id: int) -> dict:
    db = get_db()
    job = _load_job(db, job_id)
    if job is None:
        raise NotFoundError("Job not found")
    company = db.execute(
        "SELECT company_name FROM company_profiles WHERE user_id = ?", (job["employer_id"],)
    ).fetchone()
    return {
        "id": job["id"],
        "employer_id": job["employer_id"],
        "title": job["title"],
        "description": job["description"],
        "company_name": company["company_name"] if company else "",
        "required_skills": _job_skills(db, job["id"]),
    }


def get_owned_job(actor_id: int, job_id: int) -> dict:
    """Load a job for management operations (edit/delete/applicants/slots).

    Enforces the FP-EMP-2 / FP-AUTH-3 boundary *before* returning any content:
    a missing job raises 404 and a foreign posting raises 403 — including for
    reads of the edit form, not just writes.
    """
    db = get_db()
    job = _load_job(db, job_id)
    if job is None:
        raise NotFoundError("Job not found")
    if job["employer_id"] != actor_id:
        raise AuthorizationError("You do not own this job posting")
    return get_job(job_id)


def list_employer_jobs(employer_id: int) -> list[dict]:
    db = get_db()
    jobs = db.execute(
        "SELECT * FROM jobs WHERE employer_id = ? ORDER BY id", (employer_id,)
    ).fetchall()
    result = []
    for job in jobs:
        applicant_count = db.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE job_id = ?", (job["id"],)
        ).fetchone()["n"]
        slot_count = db.execute(
            "SELECT COUNT(*) AS n FROM interview_slots WHERE job_id = ?", (job["id"],)
        ).fetchone()["n"]
        result.append(
            {
                "id": job["id"],
                "title": job["title"],
                "description": job["description"],
                "required_skills": _job_skills(db, job["id"]),
                "applicant_count": applicant_count,
                "slot_count": slot_count,
            }
        )
    return result


def list_jobs_with_scores(candidate_id: int) -> list[dict]:
    """All current jobs with match score, sorted for the candidate dashboard (FP-CAN-2)."""
    db = get_db()
    candidate_skills = [
        r["skill"]
        for r in db.execute("SELECT skill FROM candidate_skills WHERE user_id = ?", (candidate_id,))
    ]
    rows = []
    for job in db.execute("SELECT * FROM jobs ORDER BY id").fetchall():
        company = db.execute(
            "SELECT company_name FROM company_profiles WHERE user_id = ?", (job["employer_id"],)
        ).fetchone()
        required = _job_skills(db, job["id"])
        rows.append(
            {
                "job_id": job["id"],
                "title": job["title"],
                "description": job["description"],
                "company_name": company["company_name"] if company else "",
                "required_skills": required,
                "score": match_score(candidate_skills, required),
            }
        )
    return sort_jobs_for_candidate(rows)
