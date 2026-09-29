"""Applications: apply-once, status transitions, applicant management (FP-CAN-3, FP-EMP-3)."""

from app.db import get_db, transaction
from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.matching import match_score, sort_applicants_for_employer
from app.timeutils import utc_now_iso

STATUSES = ("Pending", "Interviewing", "Rejected", "Accepted")


def has_applied(candidate_id: int, job_id: int) -> bool:
    row = get_db().execute(
        "SELECT 1 FROM applications WHERE job_id = ? AND candidate_id = ?",
        (job_id, candidate_id),
    ).fetchone()
    return row is not None


def apply_to_job(candidate_id: int, job_id: int) -> int:
    """Apply once per job; a new application starts as Pending (FP-CAN-3)."""
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise NotFoundError("Job not found")
    existing = db.execute(
        "SELECT id FROM applications WHERE job_id = ? AND candidate_id = ?",
        (job_id, candidate_id),
    ).fetchone()
    if existing is not None:
        raise ConflictError("Application already submitted")
    with transaction():
        cur = db.execute(
            "INSERT INTO applications (job_id, candidate_id, status, created_at) VALUES (?, ?, 'Pending', ?)",
            (job_id, candidate_id, utc_now_iso()),
        )
        return cur.lastrowid


def list_my_applications(candidate_id: int) -> list[dict]:
    """The candidate's own applications with job, employer, status, and booking (FP-CAN-3)."""
    db = get_db()
    rows = db.execute(
        """
        SELECT a.id AS application_id, a.status, a.created_at,
               j.id AS job_id, j.title, j.description,
               u.id AS employer_id, c.company_name
        FROM applications a
        JOIN jobs j ON j.id = a.job_id
        JOIN users u ON u.id = j.employer_id
        LEFT JOIN company_profiles c ON c.user_id = u.id
        WHERE a.candidate_id = ?
        ORDER BY a.id
        """,
        (candidate_id,),
    ).fetchall()
    result = []
    for row in rows:
        booking = _booking_for_application(db, row["application_id"])
        result.append({**dict(row), "booking": booking})
    return result


def get_application_for_candidate(actor_id: int, application_id: int) -> dict:
    """One application viewed by its owning candidate (FP-CAN-3, FP-SEC-1)."""
    db = get_db()
    row = db.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    if row is None:
        raise NotFoundError("Application not found")
    if row["candidate_id"] != actor_id:
        raise AuthorizationError("You cannot view another candidate's application")
    return _application_detail(db, row)


def get_application_for_employer(actor_id: int, application_id: int) -> dict:
    """One application viewed by the employer who owns its job (FP-EMP-3)."""
    db = get_db()
    row = db.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    if row is None:
        raise NotFoundError("Application not found")
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (row["job_id"],)).fetchone()
    if job is None or job["employer_id"] != actor_id:
        raise AuthorizationError("You do not own this application's job")
    return _application_detail(db, row)


def _application_detail(db, row) -> dict:
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (row["job_id"],)).fetchone()
    company = db.execute(
        "SELECT company_name FROM company_profiles WHERE user_id = ?", (job["employer_id"],)
    ).fetchone()
    return {
        "application_id": row["id"],
        "status": row["status"],
        "job_id": job["id"],
        "title": job["title"],
        "description": job["description"],
        "employer_id": job["employer_id"],
        "company_name": company["company_name"] if company else "",
        "booking": _booking_for_application(db, row["id"]),
    }


def _booking_for_application(db, application_id: int):
    row = db.execute(
        """
        SELECT b.id AS booking_id, s.id AS slot_id, s.start_utc, s.end_utc
        FROM bookings b JOIN interview_slots s ON s.id = b.slot_id
        WHERE b.application_id = ?
        """,
        (application_id,),
    ).fetchone()
    return dict(row) if row else None


def set_status(actor_id: int, application_id: int, status: str) -> dict:
    """Set an application status. Only the owning employer may (FP-EMP-3)."""
    if status not in STATUSES:
        raise ValidationError("Status must be Pending, Interviewing, Rejected, or Accepted")
    db = get_db()
    row = db.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone()
    if row is None:
        raise NotFoundError("Application not found")
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (row["job_id"],)).fetchone()
    if job is None or job["employer_id"] != actor_id:
        raise AuthorizationError("You do not own this application's job")
    with transaction():
        db.execute(
            "UPDATE applications SET status = ? WHERE id = ?",
            (status, application_id),
        )
    # A booking, if any, stays linked when the application leaves Interviewing
    # (FP-SCHED-2): nothing else is modified here.
    return _application_detail(db, db.execute("SELECT * FROM applications WHERE id = ?", (application_id,)).fetchone())


def list_applicants(employer_id: int, job_id: int) -> list[dict]:
    """Applicants for an owned job, sorted by match score (FP-EMP-3)."""
    db = get_db()
    job = db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise NotFoundError("Job not found")
    if job["employer_id"] != employer_id:
        raise AuthorizationError("You do not own this job posting")
    required = [
        r["skill"]
        for r in db.execute("SELECT skill FROM job_skills WHERE job_id = ? ORDER BY skill", (job_id,))
    ]
    rows = db.execute(
        """
        SELECT a.id AS application_id, a.status,
               u.id AS candidate_id, p.display_name, p.resume_text
        FROM applications a
        JOIN users u ON u.id = a.candidate_id
        JOIN candidate_profiles p ON p.user_id = u.id
        WHERE a.job_id = ?
        """,
        (job_id,),
    ).fetchall()
    result = []
    for row in rows:
        skills = [
            r["skill"]
            for r in db.execute(
                "SELECT skill FROM candidate_skills WHERE user_id = ? ORDER BY skill",
                (row["candidate_id"],),
            )
        ]
        result.append(
            {
                "application_id": row["application_id"],
                "status": row["status"],
                "candidate_id": row["candidate_id"],
                "display_name": row["display_name"],
                "skills": skills,
                "score": match_score(skills, required),
                "booking": _booking_for_application(db, row["application_id"]),
            }
        )
    return sort_applicants_for_employer(result)
