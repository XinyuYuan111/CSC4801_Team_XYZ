"""Unit tests for FP-AUTH-1..3: accounts, credential storage, server-side authorization."""

import pytest

from app.errors import ConflictError


def test_fp_auth_1_registration_and_session_lifecycle(client, app, db):
    # Register a candidate: created and logged in (land on the candidate dashboard).
    response = client.register("new@example.com", "Password123!", "Candidate", display_name="New User")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert b"new@example.com" in page.data

    # Log out: session ends and protected pages redirect to login.
    response = client.logout()
    assert response.status_code == 302
    page = client.get("/dashboard")
    assert page.status_code == 302
    assert "/login" in page.headers["Location"]

    # Log back in with the same credentials.
    response = client.login("new@example.com", "Password123!")
    assert response.status_code == 302
    assert client.get("/dashboard").status_code == 200

    # Register an employer with a unique email: lands on the employer job list.
    client.logout()
    response = client.register("boss@example.com", "Password123!", "Employer", company_name="Boss Co")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/employer/jobs")

    rows = db.execute("SELECT email, role FROM users ORDER BY email").fetchall()
    emails = {row["email"] for row in rows}
    assert "new@example.com" in emails
    assert "boss@example.com" in emails
    roles = {row["email"]: row["role"] for row in rows}
    assert roles["new@example.com"] == "Candidate"
    assert roles["boss@example.com"] == "Employer"


def test_fp_auth_1_invalid_registration(client, db):
    # Unknown role.
    response = client.register("a@example.com", "Password123!", "Admin", display_name="A")
    assert response.status_code == 400
    # Short password.
    response = client.register("a@example.com", "short", "Candidate", display_name="A")
    assert response.status_code == 400
    # Candidate without display name.
    response = client.register("a@example.com", "Password123!", "Candidate", display_name="  ")
    assert response.status_code == 400
    # Employer without company name.
    response = client.register("a@example.com", "Password123!", "Employer", company_name="")
    assert response.status_code == 400
    # Invalid email.
    response = client.register("not-an-email", "Password123!", "Candidate", display_name="A")
    assert response.status_code == 400
    # Duplicate email identifier is rejected (uniqueness is case-insensitive by storage).
    assert client.register("dup@example.com", "Password123!", "Candidate", display_name="A").status_code == 302
    client.logout()
    response = client.register("dup@example.com", "Password123!", "Candidate", display_name="B")
    assert response.status_code == 409

    rows = db.execute("SELECT email FROM users WHERE email LIKE 'a@%' OR email LIKE 'not%'").fetchall()
    assert rows == []
    count = db.execute("SELECT COUNT(*) AS n FROM users WHERE email = 'dup@example.com'").fetchone()["n"]
    assert count == 1


def test_fp_auth_2_salted_hash_and_password_verification(client, app, db):
    response = client.register("hash@example.com", "Password123!", "Candidate", display_name="Hash")
    assert response.status_code == 302

    row = db.execute("SELECT password_hash FROM users WHERE email = 'hash@example.com'").fetchone()
    password_hash = row["password_hash"]
    # Never plain text, never the password itself, never reversible storage.
    assert password_hash != "Password123!"
    assert "Password123!" not in password_hash
    assert password_hash.startswith(("pbkdf2:", "scrypt:"))

    # Hashes are salted: a second user with the same password gets a different hash.
    client.logout()
    assert client.register("hash2@example.com", "Password123!", "Candidate", display_name="Hash2").status_code == 302
    row2 = db.execute("SELECT password_hash FROM users WHERE email = 'hash2@example.com'").fetchone()
    assert row2["password_hash"] != password_hash

    # Verification accepts the real password and rejects a wrong one.
    from app.security import verify_password

    assert verify_password(password_hash, "Password123!") is True
    assert verify_password(password_hash, "wrong-password") is False

    # authenticate() never hands the hash to its caller (defense in depth).
    from app.services import auth as auth_service

    with app.app_context():
        result = auth_service.authenticate("hash@example.com", "Password123!")
        assert result is not None
        assert set(result.keys()) == {"id", "email", "role"}
        assert "password_hash" not in result

    # Failed login returns 401 and no secret material.
    client.logout()
    response = client.login("hash@example.com", "wrong-password")
    assert response.status_code == 401
    assert password_hash.encode() not in response.data

    # Password hash is never rendered in any authenticated page.
    assert client.login("hash@example.com", "Password123!").status_code == 302
    for path in ("/dashboard", "/profile", "/applications"):
        page = client.get(path)
        assert page.status_code == 200
        assert password_hash.encode() not in page.data
        assert b"password_hash" not in page.data


def test_fp_auth_3_authorization_and_missing_object(client, world):
    ids = world(include_cara=True)

    # Unauthenticated GET: redirect to login (documented equivalent of 401).
    response = client.get("/dashboard")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]

    # Unauthenticated non-GET: 401.
    response = client.post("/jobs/1/apply")
    assert response.status_code == 401

    # Wrong role: candidate hitting an employer route gets 403.
    client.login("alice@test.local", "Password123!")
    response = client.get("/employer/jobs")
    assert response.status_code == 403

    # Wrong owner: employer Ben cannot edit Ana's job (403).
    client.logout()
    client.login("ben@test.local", "Password123!")
    response = client.post(
        f"/jobs/{ids['jobs']['backend']}/edit",
        data={"title": "Hijacked", "description": "Hijacked", "skills": ""},
    )
    assert response.status_code == 403

    # Missing object the caller would otherwise be allowed to access: 404.
    response = client.get("/jobs/99999")
    assert response.status_code == 404
    client.logout()
    client.login("alice@test.local", "Password123!")
    response = client.get("/candidates/99999/resume")
    assert response.status_code == 404
    response = client.get("/applications/99999")
    assert response.status_code == 404

    # Secrets never appear in responses.
    assert b"Password123!" not in client.get("/profile").data


def test_fp_auth_1_concurrent_duplicate_registration_maps_to_conflict(app, db):
    """A duplicate that wins the check-insert race maps to 409, never a 500.

    Duplicate detection is the UNIQUE(email) constraint inside the insert
    transaction (same pattern as apply_to_job), so two concurrent registrations
    cannot both pass a pre-check and crash on the second insert.
    """
    from app.services import auth as auth_service

    with app.app_context():
        auth_service.register_user(
            "race@example.com", "Password123!", "Candidate", display_name="Racer"
        )
        with pytest.raises(ConflictError) as excinfo:
            auth_service.register_user(
                "race@example.com", "Password123!", "Candidate", display_name="Other"
            )
        assert excinfo.value.status == 409
        assert excinfo.value.message == "Email already registered"

    count = db.execute(
        "SELECT COUNT(*) AS n FROM users WHERE email = 'race@example.com'"
    ).fetchone()["n"]
    assert count == 1
