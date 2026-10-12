"""System: security surface over real HTTP responses (FP-SEC-2/3/4, FP-AUTH-2).

Unlike the unit tests (which target one helper each), these end-to-end checks
feed attack payloads through registration, profiles, resumes and job forms and
inspect what the server actually renders and leaks on the wire.
"""

import re
import sqlite3
from html import unescape as html_unescape

from tests.system.conftest import Browser

XSS = "<script>alert(1)</script>"
SQLI = "'; DROP TABLE users; --"


def _text(resp) -> str:
    return resp.get_data(as_text=True)


def test_xss_payloads_are_escaped_in_every_user_controlled_field(app):
    cand, emp, viewer = Browser(app), Browser(app), Browser(app)
    assert emp.register("e@xss.test", "Password123!", "Employer", company_name=XSS).status_code == 302
    assert cand.register("c@xss.test", "Password123!", "Candidate", display_name=XSS).status_code == 302

    # Poison every text field the product has.
    assert cand.post("/profile", {"display_name": XSS, "skills": XSS}).status_code == 302
    assert cand.get("/profile").status_code == 200
    resp = cand.get("/profile")
    assert XSS not in _text(resp) or "&lt;script&gt;" in _text(resp)
    assert "<script>alert(1)</script>" not in _text(resp)

    # Find the candidate's resume URL and poison the resume too.
    cand_id = re.search(r"/candidates/(\d+)/resume", _text(cand.get("/profile"))).group(1)
    assert cand.post(f"/candidates/{cand_id}/resume", {"resume_text": XSS}).status_code == 302
    assert "<script>alert(1)</script>" not in _text(cand.get(f"/candidates/{cand_id}/resume"))

    assert emp.post("/company", {"company_name": XSS, "description": XSS}).status_code == 302
    assert emp.post("/employer/jobs/new", {"title": XSS, "description": XSS, "skills": XSS}).status_code == 302

    # Every other party that renders those fields must see escaped text only.
    pages = []
    pages.append(cand.get("/dashboard"))
    pages.append(cand.get("/profile"))
    pages.append(cand.get(f"/candidates/{cand_id}/resume"))
    pages.append(emp.get("/employer/jobs"))
    pages.append(emp.get("/company"))
    assert viewer.register("v@xss.test", "Password123!", "Candidate", display_name="Viewer").status_code == 302
    pages.append(viewer.get("/dashboard"))
    pages.append(viewer.get("/jobs/1"))

    for resp in pages:
        body = _text(resp)
        assert "<script>alert(1)</script>" not in body, f"raw XSS in {resp.request.path}"
        if XSS.replace("<", "&lt;") in body or XSS not in body:
            pass  # escaped or absent — both safe
        else:
            raise AssertionError(f"unescaped payload in {resp.request.path}")


def test_sql_metacharacters_are_data_not_code(app, db):
    cand = Browser(app)
    # Apostrophes / SQL metacharacters in identifiers must be stored as-is.
    assert cand.register(f"o{SQLI}@sql.test".replace(" ", "")[:40], "Password123!", "Candidate",
                         display_name=SQLI).status_code == 302
    # The DB still has its tables and the hostile name is a plain value.
    names = [
        r["display_name"]
        for r in db.execute("SELECT display_name FROM candidate_profiles")
    ]
    assert SQLI in names
    assert db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"] >= 1

    # Hostile skill/job text round-trips as data (may be HTML-escaped in the
    # source; unescape before comparing). Skills are stored lowercased.
    assert cand.post("/profile", {"display_name": "Safe", "skills": SQLI}).status_code == 302
    profile_body = _text(cand.get("/profile"))
    assert SQLI.lower() in html_unescape(profile_body).lower()
    emp = Browser(app)
    assert emp.register("e@sql.test", "Password123!", "Employer", company_name="Co").status_code == 302
    assert emp.post("/employer/jobs/new", {"title": SQLI, "description": SQLI, "skills": SQLI}).status_code == 302
    assert SQLI in html_unescape(_text(emp.get("/employer/jobs")))


def test_password_hash_never_reaches_any_response(app, db):
    cand = Browser(app)
    assert cand.register("secret@pw.test", "SuperSecret123!", "Candidate", display_name="S").status_code == 302
    cand_id = re.search(r"/candidates/(\d+)/resume", _text(cand.get("/profile"))).group(1)

    with app.app_context():
        row = db.execute("SELECT password_hash FROM users WHERE email = 'secret@pw.test'").fetchone()
    assert row and row["password_hash"]

    pages = [
        cand.get("/dashboard"),
        cand.get("/profile"),
        cand.get(f"/candidates/{cand_id}/resume"),
        cand.get("/applications"),
        cand.get("/jobs/1") if cand.get("/jobs/1").status_code == 200 else cand.get("/"),
    ]
    for resp in pages:
        body = _text(resp)
        assert row["password_hash"] not in body
        assert "SuperSecret123!" not in body
        assert "password_hash" not in body


def test_csrf_missing_or_wrong_token_is_rejected(app):
    cand = Browser(app)
    assert cand.register("c@csrf.test", "Password123!", "Candidate", display_name="C").status_code == 302
    # No token at all.
    resp = cand.post_without_csrf("/profile", {"display_name": "Hacked", "skills": ""})
    assert resp.status_code == 403
    # Wrong token.
    resp = cand.client.post(
        "/profile",
        data={"display_name": "Hacked", "skills": "", "csrf_token": "forged-token"},
    )
    assert resp.status_code == 403
    # Profile untouched.
    assert "Hacked" not in _text(cand.get("/profile"))


def test_every_post_form_embeds_csrf_token(app):
    """Browser-faithful requirement: a user cannot submit a form that lacks the token."""
    emp = Browser(app)
    cand = Browser(app)
    assert emp.register("e@form.test", "Password123!", "Employer", company_name="C").status_code == 302
    assert cand.register("c@form.test", "Password123!", "Candidate", display_name="C").status_code == 302
    assert emp.post("/employer/jobs/new", {"title": "J", "description": "d", "skills": ""}).status_code == 302
    assert emp.post("/employer/slots", {"job_id": 1, "start_utc": "2031-06-01T15:00:00Z"}).status_code == 302
    assert cand.post("/jobs/1/apply", {}).status_code == 302

    cand_id = re.search(r"/candidates/(\d+)/resume", _text(cand.get("/profile"))).group(1)
    pages = [
        ("/login", Browser(app)),
        ("/register", Browser(app)),
        ("/profile", cand),
        (f"/candidates/{cand_id}/resume", cand),
        ("/applications", cand),
        ("/applications/1", cand),
        ("/jobs/1", cand),
        ("/company", emp),
        ("/employer/jobs", emp),
        ("/employer/jobs/new", emp),
        ("/jobs/1/edit", emp),
        ("/employer/slots", emp),
        ("/jobs/1/applicants", emp),
    ]
    for path, browser in pages:
        resp = browser.get(path)
        if resp.status_code != 200:
            continue
        body = _text(resp)
        forms = re.findall(r"<form[^>]*method=\"post\"[^>]*>(.*?)</form>", body, re.S | re.I)
        for form in forms:
            assert 'name="csrf_token"' in form, f"POST form on {path} lacks csrf_token field"


def test_sqlite_file_uses_bound_parameters_only():
    """Static check of the data-access layer: no string-built SQL with f-strings/%."""
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[2] / "app"
    offenders = []
    for sub in ("services", "routes"):
        for py in (root / sub).rglob("*.py"):
            text = py.read_text(encoding="utf-8")
            for pattern in (r'execute\(\s*f"', r"execute\(\s*f'", r'execute\(\s*"%', r"execute\(\s*'%"):
                if re.search(pattern, text):
                    offenders.append((py.name, pattern))
    assert not offenders, f"possible string-built SQL: {offenders}"
