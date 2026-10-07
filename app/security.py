"""Security helpers: password hashing, HTML escaping, CSRF tokens.

Password storage uses werkzeug's established password hash (scrypt/PBKDF2),
never plain text or a reversible cipher (FP-AUTH-2). Templates rely on Jinja2
autoescaping for user-controlled text (FP-SEC-3); ``escape_html`` is the
explicit helper for any text turned into markup outside a template.
"""

import hmac
import secrets

from markupsafe import escape
from werkzeug.security import check_password_hash, generate_password_hash


def hash_password(password: str) -> str:
    """Hash a password with an established, salted password-hashing function."""
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    """Constant-time verification of a password against its stored hash."""
    return check_password_hash(password_hash, password)


def escape_html(text: str) -> str:
    """Escape user-controlled text so it is never executable markup (FP-SEC-3)."""
    return str(escape(text if text is not None else ""))


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_token_valid(session_token: str, submitted_token: str) -> bool:
    # Generated tokens are ASCII. Reject malformed form input before passing
    # it to compare_digest, which raises TypeError for non-ASCII strings.
    return (
        bool(session_token)
        and bool(submitted_token)
        and session_token.isascii()
        and submitted_token.isascii()
        and hmac.compare_digest(session_token, submitted_token)
    )
