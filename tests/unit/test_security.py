"""Unit tests for FP-SEC-1..3: object access boundaries, SQL injection, XSS."""

import pytest

from app.errors import AuthorizationError
from app.security import escape_html
from app.services import applications as applications_service
from app.services import jobs as jobs_service
from app.services import profiles as profiles_service
from app.services import scheduling as scheduling_service
from tests.conftest import make_future_slot_start, make_slot_end


def test_fp_sec_1_candidate_cannot_access_other_resume_or_application(client, app, world):
    ids = world()
    alice, bob = ids["users"]["alice"], ids["users"]["bob"]
    backend = ids["jobs"]["backend"]

    with app.app_context():
        profiles_service.replace_resume(alice, alice, "SECRET-RESUME-CONTENT")
        alice_app = applications_service.apply_to_job(alice, backend)

    # Direct URL with a changed object id must not bypass authorization.
    client.login("bob@test.local", "Password123!")
    assert client.get(f"/candidates/{alice}/resume").status_code == 403
    assert client.post(
        f"/candidates/{alice}/resume", data={"resume_text": "overwritten"}
    ).status_code == 403
    assert client.get(f"/applications/{alice_app}").status_code == 403

    # The stolen resume is unchanged and never leaks into Bob's pages.
    with app.app_context():
        assert profiles_service.read_resume(alice, alice) == "SECRET-RESUME-CONTENT"
    page = client.get("/applications")
    assert b"SECRET-RESUME-CONTENT" not in page.data


def test_fp_sec_1_employer_cannot_modify_others_job_or_read_applicants(client, app, world):
    ids = world()
    ana, ben, alice = ids["users"]["ana"], ids["users"]["ben"], ids["users"]["alice"]
    backend = ids["jobs"]["backend"]

    with app.app_context():
        applications_service.apply_to_job(alice, backend)

    # Ben attacks Ana's job object ids directly.
    client.login("ben@test.local", "Password123!")
    assert client.get(f"/jobs/{backend}/applicants").status_code == 403
    assert client.get(f"/jobs/{backend}/edit").status_code == 403
    assert client.post(
        f"/jobs/{backend}/edit", data={"title": "Hijack", "description": "Hijack", "skills": ""}
    ).status_code == 403
    assert client.post(f"/jobs/{backend}/delete").status_code == 403

    # The job is unchanged and Ana's applicant data never reaches Ben.
    with app.app_context():
        assert jobs_service.get_job(backend)["title"] == "Backend Engineer"
    page = client.get("/employer/jobs")
    assert b"Backend Engineer" not in page.data  # not in Ben's own list either


def test_fp_sec_1_candidate_cannot_book_with_others_application(client, app, world):
    ids = world()
    ana, alice, bob = ids["users"]["ana"], ids["users"]["alice"], ids["users"]["bob"]
    backend = ids["jobs"]["backend"]

    with app.app_context():
        alice_app = applications_service.apply_to_job(alice, backend)
        applications_service.set_status(ana, alice_app, "Interviewing")
        start = make_future_slot_start()
        slot_id = scheduling_service.create_slot(ana, backend, start, make_slot_end(start))

    # Bob submits a booking form that points at Alice's application id.
    client.login("bob@test.local", "Password123!")
    response = client.post(
        "/bookings", data={"application_id": alice_app, "slot_id": slot_id}
    )
    assert response.status_code == 403

    with app.app_context():
        from app.db import get_db

        assert get_db().execute("SELECT COUNT(*) AS n FROM bookings").fetchone()["n"] == 0
        # Bob also cannot reach Alice's application detail to learn about slots.
        with pytest.raises(AuthorizationError):
            applications_service.get_application_for_candidate(bob, alice_app)


def test_fp_sec_2_sql_metacharacters_stay_bound(client, app, db):
    """SQL metacharacters are stored as data, never executed (parameterized access)."""
    evil_title = "'; DROP TABLE users; --"
    evil_skill = "x' OR '1'='1"

    client.register("safe@example.com", "Password123!", "Employer", company_name="Safe Co")
    response = client.post(
        "/employer/jobs/new",
        data={"title": evil_title, "description": evil_skill, "skills": evil_skill},
    )
    assert response.status_code == 302

    rows = db.execute("SELECT title, description FROM jobs").fetchall()
    assert any(row["title"] == evil_title for row in rows)  # bound as a value
    # The injection did not execute: the users table still exists and is intact.
    users = db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
    assert users == 1

    # Metacharacters in lookup keys are also bound, not concatenated.
    from app.services import auth as auth_service

    assert auth_service.authenticate("'; DELETE FROM users WHERE '1'='1", "x") is None
    assert db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] == 1

    # Login with the real account still works after the attack inputs.
    client.logout()
    assert client.login("safe@example.com", "Password123!").status_code == 302


def test_fp_sec_3_script_tag_is_escaped(client, app, world):
    """<script>alert(1)</script> never reaches the browser as executable markup."""
    payload = "<script>alert(1)</script>"
    ids = world()
    alice = ids["users"]["alice"]

    with app.app_context():
        profiles_service.replace_resume(alice, alice, payload)
        profiles_service.update_candidate_profile(alice, payload, "Python")
        jobs_service.create_job(ids["users"]["ana"], payload, payload, payload)

    client.login("alice@test.local", "Password123!")
    resume_page = client.get(f"/candidates/{alice}/resume")
    assert resume_page.status_code == 200
    assert b"<script>alert(1)</script>" not in resume_page.data
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in resume_page.data

    profile_page = client.get("/profile")
    assert b"<script>alert(1)</script>" not in profile_page.data

    dashboard = client.get("/dashboard")
    assert b"<script>alert(1)</script>" not in dashboard.data
    assert b"&lt;script&gt;alert(1)&lt;/script&gt;" in dashboard.data

    # The explicit escaping helper used outside templates behaves the same way.
    assert "<script>" not in escape_html(payload)
    assert "&lt;script&gt;" in escape_html(payload)


def test_fp_sec_4_test_isolation_and_no_secrets(app, client, world):
    """Tests run against an isolated database and never expose password hashes."""
    assert "test.sqlite3" in app.config["DATABASE"]  # tmp_path fixture, not the app default
    assert app.config["SECRET_KEY"] == "unit-test-secret-key"

    ids = world()
    with app.app_context():
        from app.db import get_db

        row = get_db().execute("SELECT password_hash FROM users LIMIT 1").fetchone()
        password_hash = row["password_hash"]

    client.login("alice@test.local", "Password123!")
    for path in ("/dashboard", "/profile", "/applications"):
        page = client.get(path)
        assert password_hash.encode() not in page.data
