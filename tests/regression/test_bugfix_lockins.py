"""Regression suite: lock in every historical bug fix (see REVIEW.md 历史记录).

Each test guards one fix from the earlier review rounds so a future refactor
cannot silently reintroduce it. These are HTTP-level lock-ins; the unit suite
asserts the same requirements at the logic level, this suite pins the *bug
class* that was once observed in the running product.
"""

import re

import pytest

from app.db import get_db
from tests.system.conftest import Browser


def _text(resp) -> str:
    return resp.get_data(as_text=True)


# --- 修复①：未登录 POST 曾被 CSRF 检查遮蔽返回 403（应先 401） -------------


def test_regression_unauthenticated_post_is_401_not_csrf_403(app):
    b = Browser(app)
    # No login, no CSRF: authentication must win (401), not CSRF (403).
    resp = b.post_without_csrf("/profile", {"display_name": "x", "skills": ""})
    assert resp.status_code == 401
    resp = b.post_without_csrf("/bookings", {"application_id": 1, "slot_id": 1})
    assert resp.status_code == 401


# --- 修复②：非 ASCII CSRF token 曾触发 500（compare_digest TypeError） ------


def test_regression_non_ascii_csrf_token_is_403_not_500(app):
    b = Browser(app)
    assert b.register("c@csrr.test", "Password123!", "Candidate", display_name="C").status_code == 302
    resp = b.client.post(
        "/profile",
        data={"display_name": "x", "skills": "", "csrf_token": "令牌tokenにほんご"},
    )
    assert resp.status_code == 403, _text(resp)[:300]


# --- 修复③：雇主列表曾把过期时段标为 available ------------------------------


def test_regression_past_slot_shows_expired_not_available(app, db):
    emp = Browser(app)
    assert emp.register("e@exp.test", "Password123!", "Employer", company_name="C").status_code == 302
    assert emp.post("/employer/jobs/new", {"title": "J", "description": "d", "skills": ""}).status_code == 302
    # Inject a past slot directly (the service layer correctly refuses to create one).
    with app.app_context():
        db.execute(
            "INSERT INTO interview_slots (job_id, employer_id, start_utc, end_utc, created_at)"
            " VALUES (1, 1, '2020-01-01T15:00:00Z', '2020-01-01T15:30:00Z', '2020-01-01T00:00:00Z')",
        )
    html = _text(emp.get("/employer/slots"))
    assert 'class="muted">expired</span>' in html
    assert 'class="muted">available</span>' not in html  # state cell must not say available


# --- 修复④：GET /jobs/<id>/edit 曾缺属主校验（越权泄露） --------------------


def test_regression_foreign_employer_edit_form_leaks_nothing(app):
    ana = Browser(app)
    ben = Browser(app)
    assert ana.register("ana@reg.test", "Password123!", "Employer", company_name="A").status_code == 302
    assert ben.register("ben@reg.test", "Password123!", "Employer", company_name="B").status_code == 302
    assert ana.post(
        "/employer/jobs/new", {"title": "SecretProject", "description": "TopSecretDesc", "skills": "Rust"}
    ).status_code == 302
    resp = ben.get("/jobs/1/edit")
    assert resp.status_code == 403
    body = _text(resp)
    assert "SecretProject" not in body and "TopSecretDesc" not in body


# --- 修复⑤：雇主 GET /applications/<id> 曾 403（应与 SPEC 一致 200） --------


def test_regression_employer_can_view_own_jobs_application_detail(app):
    ana = Browser(app)
    alice = Browser(app)
    assert ana.register("ana@reg2.test", "Password123!", "Employer", company_name="A").status_code == 302
    assert alice.register("al@reg2.test", "Password123!", "Candidate", display_name="Al").status_code == 302
    assert ana.post("/employer/jobs/new", {"title": "J", "description": "d", "skills": ""}).status_code == 302
    assert alice.post("/jobs/1/apply", {}).status_code == 302
    apps = re.findall(r"/applications/(\d+)/status", _text(ana.get("/jobs/1/applicants")))
    resp = ana.get(f"/applications/{apps[0]}")
    assert resp.status_code == 200
    assert "Back to applicants" in _text(resp)  # 修复⑪：雇主返回链接指向 applicants


# --- 修复⑥：并发/重复投递曾可能 500（应 409 + 唯一约束） -------------------


def test_regression_duplicate_apply_is_409_and_single_row(app, db):
    alice = Browser(app)
    emp = Browser(app)
    assert emp.register("e@dup.test", "Password123!", "Employer", company_name="C").status_code == 302
    assert alice.register("a@dup.test", "Password123!", "Candidate", display_name="A").status_code == 302
    assert emp.post("/employer/jobs/new", {"title": "J", "description": "d", "skills": ""}).status_code == 302
    assert alice.post("/jobs/1/apply", {}).status_code == 302
    resp = alice.post("/jobs/1/apply", {})
    assert resp.status_code == 409
    assert "Application already submitted" in _text(resp)
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"] == 1


def test_regression_duplicate_registration_is_409_not_500(app):
    b = Browser(app)
    assert b.register("dup@reg.test", "Password123!", "Candidate", display_name="D").status_code == 302
    b2 = Browser(app)
    resp = b2.register("DUP@reg.test", "Password123!", "Candidate", display_name="D2")
    assert resp.status_code == 409
    assert "Email already registered" in _text(resp)


# --- 修复⑦：authenticate() 曾返回 password_hash ---------------------------


def test_regression_password_hash_stays_inside_auth_module(app, db):
    b = Browser(app)
    assert b.register("h@reg.test", "HashPass123!", "Candidate", display_name="H").status_code == 302
    from app.services import auth as auth_service

    with app.app_context():
        user = auth_service.authenticate("h@reg.test", "HashPass123!")
    assert set(user.keys()) == {"id", "email", "role"}


# --- 修复⑧：依赖检查曾不在事务内（删有依赖数据应 409 且数据不变） ----------


def test_regression_delete_with_dependents_is_409_and_atomic(app, db):
    alice = Browser(app)
    emp = Browser(app)
    assert emp.register("e@del.test", "Password123!", "Employer", company_name="C").status_code == 302
    assert alice.register("a@del.test", "Password123!", "Candidate", display_name="A").status_code == 302
    assert emp.post("/employer/jobs/new", {"title": "J", "description": "d", "skills": ""}).status_code == 302
    assert emp.post("/employer/slots", {"job_id": 1, "start_utc": "2031-01-01T15:00:00Z"}).status_code == 302
    assert alice.post("/jobs/1/apply", {}).status_code == 302
    resp = emp.post("/jobs/1/delete", {})
    assert resp.status_code == 409
    with app.app_context():
        db = get_db()
        assert db.execute("SELECT COUNT(*) AS n FROM jobs").fetchone()["n"] == 1
        assert db.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"] == 1
        assert db.execute("SELECT COUNT(*) AS n FROM interview_slots").fetchone()["n"] == 1


# --- 修复⑨：FK 竞态曾 500（应映射 404/409） --------------------------------


def test_regression_fk_race_maps_to_404(app, db):
    """Apply whose job vanishes mid-INSERT must be 404, never 500.

    A BEFORE INSERT trigger deletes the job behind the service's back — the
    exact FK race ``translate_integrity_error`` was built for.
    """
    from app.errors import NotFoundError
    from app.services import applications as applications_service

    alice = Browser(app)
    emp = Browser(app)
    assert emp.register("e@fk.test", "Password123!", "Employer", company_name="C").status_code == 302
    assert alice.register("a@fk.test", "Password123!", "Candidate", display_name="A").status_code == 302
    assert emp.post("/employer/jobs/new", {"title": "J", "description": "d", "skills": ""}).status_code == 302

    with app.app_context():
        user_id = get_db().execute(
            "SELECT id FROM users WHERE email='a@fk.test'"
        ).fetchone()["id"]
        db.execute(
            "CREATE TRIGGER job_vanishes BEFORE INSERT ON applications "
            "BEGIN "
            "  DELETE FROM job_skills WHERE job_id = NEW.job_id; "
            "  DELETE FROM jobs WHERE id = NEW.job_id; "
            "END"
        )
        with pytest.raises(NotFoundError) as excinfo:
            applications_service.apply_to_job(user_id, 1)
        assert excinfo.value.status == 404
        # No orphan application row. (The trigger's DELETE runs inside the same
        # transaction as the failed INSERT, so the ROLLBACK correctly restores
        # the job — a real cross-connection race would have removed it for good,
        # which the RESTRICT FK would then report the same way.)
        assert db.execute("SELECT COUNT(*) AS n FROM applications").fetchone()["n"] == 0


# --- 修复⑩：注册文案与种子技能不一致（种子演示数据行） ---------------------


def test_regression_seed_skills_match_documented_examples(app):
    from app.seed import seed_demo_data

    with app.app_context():
        seed_demo_data()
    b = Browser(app)
    assert b.login("alice@demo.local", "DemoPass123!").status_code == 302
    html = _text(b.get("/dashboard"))
    assert re.search(r'<td class="score">100</td>\s*<td>Backend Engineer</td>', html)
    assert "python" in html.lower() and "sql" in html.lower()
