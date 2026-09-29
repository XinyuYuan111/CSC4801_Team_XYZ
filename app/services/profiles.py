"""Candidate profiles, private resumes, and company profiles (FP-CAN-1, FP-EMP-1)."""

from app.db import get_db, transaction
from app.errors import AuthorizationError, NotFoundError, ValidationError
from app.matching import parse_skills_text

RESUME_MAX_LEN = 20000


def get_candidate_profile(candidate_id: int) -> dict:
    db = get_db()
    row = db.execute(
        "SELECT user_id, display_name, resume_text FROM candidate_profiles WHERE user_id = ?",
        (candidate_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("Candidate not found")
    skills = [
        r["skill"]
        for r in db.execute(
            "SELECT skill FROM candidate_skills WHERE user_id = ? ORDER BY skill",
            (candidate_id,),
        )
    ]
    return {"user_id": row["user_id"], "display_name": row["display_name"], "resume_text": row["resume_text"], "skills": skills}


def update_candidate_profile(candidate_id: int, display_name: str, skills_text: str) -> dict:
    """Update the caller's own display name and technical skills.

    Skills are stored normalized (trimmed, lowercased, deduplicated) in
    ``candidate_skills`` so the matching function can read them directly.
    """
    display_name = (display_name or "").strip()
    if not display_name:
        raise ValidationError("Display name is required")
    skills = parse_skills_text(skills_text or "")
    db = get_db()
    exists = db.execute("SELECT 1 FROM candidate_profiles WHERE user_id = ?", (candidate_id,)).fetchone()
    if exists is None:
        raise NotFoundError("Candidate not found")
    with transaction():
        db.execute(
            "UPDATE candidate_profiles SET display_name = ? WHERE user_id = ?",
            (display_name, candidate_id),
        )
        db.execute("DELETE FROM candidate_skills WHERE user_id = ?", (candidate_id,))
        db.executemany(
            "INSERT INTO candidate_skills (user_id, skill) VALUES (?, ?)",
            [(candidate_id, skill) for skill in skills],
        )
    return get_candidate_profile(candidate_id)


def replace_resume(actor_id: int, candidate_id: int, resume_text: str) -> None:
    """Replace the resume of ``candidate_id``. Only the owner may do this (FP-CAN-1)."""
    _check_resume_access(actor_id, candidate_id)
    if len(resume_text or "") > RESUME_MAX_LEN:
        raise ValidationError(f"Resume must be at most {RESUME_MAX_LEN} characters")
    with transaction():
        get_db().execute(
            "UPDATE candidate_profiles SET resume_text = ? WHERE user_id = ?",
            (resume_text or "", candidate_id),
        )


def read_resume(actor_id: int, candidate_id: int) -> str:
    """Read a resume. Only the owning candidate may do this (FP-CAN-1, FP-SEC-1)."""
    _check_resume_access(actor_id, candidate_id)
    row = get_db().execute(
        "SELECT resume_text FROM candidate_profiles WHERE user_id = ?",
        (candidate_id,),
    ).fetchone()
    return row["resume_text"]


def _check_resume_access(actor_id: int, candidate_id: int) -> None:
    if actor_id is None:
        raise AuthorizationError("Please log in")
    db = get_db()
    target = db.execute("SELECT user_id FROM candidate_profiles WHERE user_id = ?", (candidate_id,)).fetchone()
    if target is None:
        raise NotFoundError("Candidate not found")
    if actor_id != candidate_id:
        raise AuthorizationError("Resumes are private to their owner")


def get_company(employer_id: int) -> dict:
    row = get_db().execute(
        "SELECT user_id, company_name, description FROM company_profiles WHERE user_id = ?",
        (employer_id,),
    ).fetchone()
    if row is None:
        raise NotFoundError("Company not found")
    return dict(row)


def update_company(employer_id: int, company_name: str, description: str) -> dict:
    company_name = (company_name or "").strip()
    if not company_name:
        raise ValidationError("Company name is required")
    db = get_db()
    exists = db.execute("SELECT 1 FROM company_profiles WHERE user_id = ?", (employer_id,)).fetchone()
    if exists is None:
        raise NotFoundError("Company not found")
    with transaction():
        db.execute(
            "UPDATE company_profiles SET company_name = ?, description = ? WHERE user_id = ?",
            (company_name, (description or "").strip(), employer_id),
        )
    return get_company(employer_id)
