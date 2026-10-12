"""Robustness / fuzz-style suite: hostile and malformed input must never 500.

The contract under test: every user-controlled value — wrong type, oversized,
control characters, null bytes, unicode edge cases, tampered cookies — yields a
clean 4xx/redirect and leaves the database consistent. A 500 anywhere here is a
product defect even if the functional suites stay green.
"""

import re
import sqlite3

import pytest

from app.db import get_db
from tests.system.conftest import Browser

NASTY = [
    pytest.param("", id="empty"),
    pytest.param(" ", id="space"),
    pytest.param("\x00", id="null-byte"),
    pytest.param("\x00\x01\x02", id="control-bytes"),
    pytest.param("\n\r\n", id="newlines"),
    pytest.param("\t", id="tab"),
    pytest.param("A" * 50_000, id="50k-As"),
    pytest.param("<script>alert(1)</script>", id="xss-script"),
    pytest.param("'; DROP TABLE users; --", id="sqli-drop"),
    pytest.param("${7*7}", id="ssti"),
    pytest.param("../../../etc/passwd", id="traversal"),
    pytest.param("%00", id="percent-null"),
    pytest.param("%2e%2e%2f", id="percent-traversal"),
    pytest.param("🙂" * 200, id="emoji-spam"),
    pytest.param("中文字段测试值", id="cjk"),
    pytest.param("‮‭", id="rtl-override"),
    pytest.param("line1\nline2\r\nline3", id="multiline"),
]


def _text(resp) -> str:
    return resp.get_data(as_text=True)


@pytest.fixture()
def actor(app):
    b = Browser(app)
    assert b.register("rob@act.test", "Password123!", "Candidate", display_name="Rob").status_code == 302
    return b


@pytest.fixture()
def employer(app):
    b = Browser(app)
    assert b.register("rob@emp.test", "Password123!", "Employer", company_name="RobCo").status_code == 302
    return b


@pytest.mark.parametrize("payload", NASTY)
def test_profile_update_with_hostile_input_never_500s(app, actor, payload):
    resp = actor.post("/profile", {"display_name": payload, "skills": payload})
    assert resp.status_code in (200, 302, 400), f"{payload!r} -> {resp.status_code}"
    assert resp.status_code != 500
    # Page still renders afterwards.
    assert actor.get("/profile").status_code == 200


@pytest.mark.parametrize("payload", NASTY)
def test_resume_with_hostile_input_never_500s(app, actor, payload):
    import re as _re

    cand_id = _re.search(r"/candidates/(\d+)/resume", _text(actor.get("/profile"))).group(1)
    resp = actor.post(f"/candidates/{cand_id}/resume", {"resume_text": payload})
    assert resp.status_code in (200, 302, 400), f"{payload!r} -> {resp.status_code}"
    assert actor.get(f"/candidates/{cand_id}/resume").status_code == 200


@pytest.mark.parametrize("payload", NASTY)
def test_job_and_company_fields_with_hostile_input_never_500s(app, employer, payload):
    for path, data in (
        ("/company", {"company_name": payload, "description": payload}),
        ("/employer/jobs/new", {"title": payload, "description": payload, "skills": payload}),
    ):
        resp = employer.post(path, data)
        assert resp.status_code in (200, 302, 400), f"{path} {payload!r} -> {resp.status_code}"
    assert employer.get("/company").status_code == 200
    assert employer.get("/employer/jobs").status_code == 200


@pytest.mark.parametrize("payload", NASTY)
def test_auth_fields_with_hostile_input_never_500s(app, payload):
    b = Browser(app)
    assert b.get("/register").status_code == 200  # pick up CSRF like a browser
    resp = b.post(
        "/register",
        {"email": payload, "password": payload, "role": payload,
         "display_name": payload, "company_name": payload},
    )
    assert resp.status_code in (200, 302, 400, 409), f"register {payload!r} -> {resp.status_code}"
    assert b.get("/login").status_code == 200
    resp = b.post("/login", {"email": payload, "password": payload})
    assert resp.status_code in (200, 302, 400, 401), f"login {payload!r} -> {resp.status_code}"


def test_hostile_slot_times_never_500(app, employer):
    assert employer.post("/employer/jobs/new", {"title": "J", "description": "d", "skills": ""}).status_code == 302
    for bad in ("", "not-a-date", "2031-13-45T99:99:99Z", "0000-00-00", "\x00" * 8, "A" * 10_000,
                "9999-12-31T23:45:00Z", "0001-01-01T00:00:00+08:00",
                "2031-06-01T15:00:00+99:99", "9999-99-99T99:99:99.999999Z"):
        resp = employer.post("/employer/slots", {"job_id": 1, "start_utc": bad})
        assert resp.status_code in (200, 302, 400), f"{bad!r} -> {resp.status_code}"
    # And a valid one still works after the abuse.
    assert employer.post("/employer/slots", {"job_id": 1, "start_utc": "2031-06-01T15:00:00Z"}).status_code == 302


@pytest.mark.parametrize("path", [
    "/jobs/abc",
    "/jobs/1.5",
    "/jobs/-1",
    "/jobs/0",
    "/applications/abc",
    "/applications/-5",
    "/candidates/x/resume",
    "/slots/NaN/delete",
])
def test_non_integer_ids_in_urls_are_clean_404s(app, actor, path):
    resp = actor.get(path)
    assert resp.status_code in (302, 400, 404), f"{path} -> {resp.status_code}"
    assert resp.status_code != 500


def test_oversized_integer_id_is_404_not_500(app, actor):
    """Huge-but-legal int in the URL must be 404, not an unhandled OverflowError.

    The ``<int:...>`` converter accepts arbitrary-length integers; binding them
    into SQLite raises OverflowError and the request becomes a 500.
    """
    app.config["PROPAGATE_EXCEPTIONS"] = False
    resp = actor.get("/jobs/999999999999999999999")
    assert resp.status_code == 404


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE", "TRACE"])
def test_unsupported_http_methods_get_405_or_404(app, actor, method):
    for path in ("/profile", "/dashboard", "/jobs/1", "/login", "/applications"):
        resp = actor.client.open(path, method=method)
        assert resp.status_code in (404, 405), f"{method} {path} -> {resp.status_code}"


def test_options_requests_get_standard_auto_response(app, actor):
    """Flask's automatic OPTIONS reply is a normal 200 with an Allow header."""
    for path in ("/profile", "/login", "/jobs/1"):
        resp = actor.client.open(path, method="OPTIONS")
        assert resp.status_code in (200, 405), f"OPTIONS {path} -> {resp.status_code}"
        assert resp.status_code != 500


def test_json_body_instead_of_form_never_500s(app, actor):
    resp = actor.client.post(
        "/profile",
        data='{"display_name": "x", "skills": "y"}',
        content_type="application/json",
    )
    assert resp.status_code in (200, 400, 401, 403)
    assert resp.status_code != 500


# --- 会话/Cookie 篡改 -------------------------------------------------------


def test_tampered_session_cookie_treated_as_anonymous(app, actor):
    """Flask signed cookies: a corrupted cookie must not authenticate."""
    client = actor.client
    cookie = client.get_cookie("session")
    assert cookie is not None, "login should set a session cookie"
    original = cookie.value
    tampered = original[:-4] + ("AAAA" if not original.endswith("AAAA") else "BBBB")
    client.set_cookie("session", tampered)
    resp = actor.get("/profile")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]
    resp = actor.client.post("/profile", data={"display_name": "x", "skills": ""})
    assert resp.status_code == 401


def test_cookie_signed_with_another_secret_is_rejected(app):
    from tests.system.conftest import Browser as B

    app.config["SECRET_KEY"] = "secret-A"
    b1 = B(app)
    assert b1.register("s@a.test", "Password123!", "Candidate", display_name="S").status_code == 302
    stolen = b1.client.get_cookie("session")
    assert stolen is not None

    app.config["SECRET_KEY"] = "secret-B"
    b2 = B(app)
    # Replay the cookie captured under a different secret: must not authenticate.
    b2.client.set_cookie("session", stolen.value)
    resp = b2.get("/profile")
    assert resp.status_code in (302, 401)


# --- 事务回滚 / 原子性（数据库触发器故障注入） ------------------------------
# sqlite3.Connection 的方法不可 monkeypatch，改用 BEFORE INSERT 触发器让
# 事务的后半段真实失败，从而检验 transaction() 的 ROLLBACK 是否完整。


def test_create_job_rolls_back_completely_when_skills_insert_fails(app, db):
    """A failure mid-transaction must leave neither the job nor partial skills."""
    from app.services import jobs as jobs_service

    with app.app_context():
        from app.services import auth as auth_service

        emp = auth_service.register_user("e@roll.test", "Password123!", "Employer", company_name="C")
        db.execute(
            "CREATE TRIGGER fail_skills BEFORE INSERT ON job_skills "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
        with pytest.raises(sqlite3.Error):
            jobs_service.create_job(emp, "Title", "Desc", "Python, SQL")

        assert db.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"] == 0
        assert db.execute("SELECT COUNT(*) AS n FROM job_skills").fetchone()["n"] == 0
        db.execute("DROP TRIGGER fail_skills")
        # The write path still works after the failure.
        assert isinstance(jobs_service.create_job(emp, "Title", "Desc", "Python, SQL"), int)


def test_update_job_rolls_back_when_skills_reinsert_fails(app, db):
    from app.services import jobs as jobs_service

    with app.app_context():
        from app.services import auth as auth_service

        emp = auth_service.register_user("e@roll2.test", "Password123!", "Employer", company_name="C")
        job_id = jobs_service.create_job(emp, "Title", "Desc", "Python")
        db.execute(
            "CREATE TRIGGER fail_skills BEFORE INSERT ON job_skills "
            "BEGIN SELECT RAISE(ABORT, 'injected failure'); END"
        )
        with pytest.raises(sqlite3.Error):
            jobs_service.update_job(emp, job_id, "NewTitle", "NewDesc", "Rust")

        # Old title and old skills intact — no half-applied edit.
        job = jobs_service.get_job(job_id)
        assert job["title"] == "Title"
        assert job["required_skills"] == ["python"]
