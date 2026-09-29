"""Account registration, authentication, and role checks (FP-AUTH-1..3)."""

from app.db import get_db, transaction
from app.errors import AuthenticationError, AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.security import hash_password, verify_password
from app.timeutils import utc_now_iso

ROLES = ("Candidate", "Employer")
MIN_PASSWORD_LEN = 8


def _validate_email(email: str) -> str:
    email = (email or "").strip()
    if "@" not in email or email.startswith("@") or email.endswith("@") or " " in email:
        raise ValidationError("Enter a valid email address")
    return email.lower()


def register_user(email: str, password: str, role: str, display_name: str = "", company_name: str = "") -> int:
    """Create a user with the given role. Email identifiers are unique (FP-AUTH-1)."""
    email = _validate_email(email)
    if role not in ROLES:
        raise ValidationError("Role must be Candidate or Employer")
    if not password or len(password) < MIN_PASSWORD_LEN:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LEN} characters")
    if role == "Candidate" and not (display_name or "").strip():
        raise ValidationError("Display name is required for candidates")
    if role == "Employer" and not (company_name or "").strip():
        raise ValidationError("Company name is required for employers")

    db = get_db()
    existing = db.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing is not None:
        raise ConflictError("Email already registered")

    password_hash = hash_password(password)
    with transaction():
        cur = db.execute(
            "INSERT INTO users (email, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
            (email, password_hash, role, utc_now_iso()),
        )
        user_id = cur.lastrowid
        if role == "Candidate":
            db.execute(
                "INSERT INTO candidate_profiles (user_id, display_name, resume_text) VALUES (?, ?, '')",
                (user_id, display_name.strip()),
            )
        else:
            db.execute(
                "INSERT INTO company_profiles (user_id, company_name, description) VALUES (?, ?, '')",
                (user_id, company_name.strip()),
            )
    return user_id


def authenticate(email: str, password: str):
    """Return ``{id, email, role}`` on success, None on bad credentials.

    The caller cannot distinguish "unknown email" from "wrong password".
    Only non-secret columns are selected, so password hashes never leave this
    module (FP-AUTH-2).
    """
    email = (email or "").strip().lower()
    user = get_db().execute(
        "SELECT id, email, role, password_hash FROM users WHERE email = ?", (email,)
    ).fetchone()
    if user is None or not verify_password(user["password_hash"], password or ""):
        return None
    return {"id": user["id"], "email": user["email"], "role": user["role"]}


def require_user(user_id) -> dict:
    """Load a user row or raise 404. Hashes are stripped from the result."""
    user = get_db().execute("SELECT id, email, role FROM users WHERE id = ?", (user_id,)).fetchone()
    if user is None:
        raise NotFoundError("User not found")
    return dict(user)


def require_role(user: dict, role: str):
    if user["role"] != role:
        raise AuthorizationError("You do not have permission to perform this action")
    return user


def login_or_401(user_id) -> dict:
    if user_id is None:
        raise AuthenticationError("Please log in")
    return require_user(user_id)
