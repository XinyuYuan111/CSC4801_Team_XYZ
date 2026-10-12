"""System: full HTTP authorization/status matrix (FP-AUTH-3, FP-SEC-1).

Every protected route is hit by every class of caller — anonymous, wrong role,
foreign owner, legitimate owner — asserting the observable 302/401/403/404/200
contract from REQUIREMENTS.md §FP-AUTH-3. System-level complement of the unit
suite's targeted boundary tests: setup happens over HTTP, assertions only look
at status codes and redirects.
"""

import pytest

from app.db import get_db
from tests.system.conftest import Browser


@pytest.fixture()
def scene(app, world):
    """World state plus one real application created over HTTP by Alice."""
    ids = world()
    alice = Browser(app)
    assert alice.login("alice@test.local", "Password123!").status_code == 302
    assert alice.get(f"/jobs/{ids['jobs']['backend']}").status_code == 200
    assert alice.post(f"/jobs/{ids['jobs']['backend']}/apply", {}).status_code == 302
    with app.app_context():
        ids["applications"]["alice_backend"] = get_db().execute(
            "SELECT id FROM applications WHERE candidate_id = ?", (ids["users"]["alice"],)
        ).fetchone()["id"]
    return ids


def _login(app, email, password) -> Browser:
    b = Browser(app)
    resp = b.login(email, password)
    assert resp.status_code == 302, f"login failed: {resp.status_code}"
    return b


# --------------------------------------------------------------------------
# Anonymous callers: GET protected -> 302 to login; POST protected -> 401
# --------------------------------------------------------------------------


def test_anonymous_gets_redirect_to_login(browser, scene):
    paths = [
        "/",
        "/dashboard",
        "/profile",
        "/applications",
        f"/applications/{scene['applications']['alice_backend']}",
        f"/jobs/{scene['jobs']['backend']}",
        f"/candidates/{scene['users']['alice']}/resume",
        "/company",
        "/employer/jobs",
        "/employer/jobs/new",
        f"/jobs/{scene['jobs']['backend']}/edit",
        f"/jobs/{scene['jobs']['backend']}/applicants",
        "/employer/slots",
    ]
    for path in paths:
        resp = browser.get(path)
        assert resp.status_code == 302, f"GET {path} -> {resp.status_code}"
        assert "/login" in resp.headers["Location"], f"GET {path} -> {resp.headers['Location']}"


def test_anonymous_post_gets_401_not_csrf_confusion(browser, scene):
    """Unauthenticated POST is 401 (auth precedes CSRF) on every protected write."""
    app_id = scene["applications"]["alice_backend"]
    cases = [
        ("/logout", {}),
        ("/profile", {}),
        ("/bookings", {"application_id": app_id, "slot_id": 1}),
        (f"/jobs/{scene['jobs']['backend']}/apply", {}),
        (f"/candidates/{scene['users']['alice']}/resume", {"resume_text": "x"}),
        (f"/jobs/{scene['jobs']['backend']}/edit", {"title": "t", "description": "d"}),
        (f"/jobs/{scene['jobs']['backend']}/delete", {}),
        (f"/applications/{app_id}/status", {"status": "Rejected", "job_id": scene["jobs"]["backend"]}),
        ("/employer/slots", {"job_id": 1, "start_utc": "2030-05-01T15:00:00Z"}),
        ("/slots/1/delete", {}),
    ]
    for path, data in cases:
        resp = browser.post_without_csrf(path, data)
        assert resp.status_code == 401, f"POST {path} -> {resp.status_code}"


# --------------------------------------------------------------------------
# Wrong-role callers: 403 Forbidden (valid session + valid CSRF)
# --------------------------------------------------------------------------


def test_employer_gets_403_on_candidate_routes(app, scene):
    emp = _login(app, "ana@test.local", "Password123!")
    paths = [
        "/dashboard",
        "/profile",
        "/applications",
        f"/candidates/{scene['users']['alice']}/resume",
    ]
    for path in paths:
        resp = emp.get(path)
        assert resp.status_code == 403, f"GET {path} -> {resp.status_code}"

    resp = emp.post(f"/jobs/{scene['jobs']['backend']}/apply", {})
    assert resp.status_code == 403
    resp = emp.post("/bookings", {"application_id": 1, "slot_id": 1})
    assert resp.status_code == 403
    resp = emp.post(f"/candidates/{scene['users']['alice']}/resume", {"resume_text": "x"})
    assert resp.status_code == 403


def test_candidate_gets_403_on_employer_routes(app, scene):
    cand = _login(app, "alice@test.local", "Password123!")
    paths = [
        "/company",
        "/employer/jobs",
        "/employer/jobs/new",
        f"/jobs/{scene['jobs']['backend']}/edit",
        f"/jobs/{scene['jobs']['backend']}/applicants",
        "/employer/slots",
    ]
    for path in paths:
        resp = cand.get(path)
        assert resp.status_code == 403, f"GET {path} -> {resp.status_code}"

    writes = [
        ("/company", {"company_name": "X", "description": "Y"}),
        ("/employer/jobs/new", {"title": "t", "description": "d", "skills": ""}),
        (f"/jobs/{scene['jobs']['backend']}/delete", {}),
        (
            f"/applications/{scene['applications']['alice_backend']}/status",
            {"status": "Rejected", "job_id": scene["jobs"]["backend"]},
        ),
        ("/employer/slots", {"job_id": scene["jobs"]["backend"], "start_utc": "2030-05-01T15:00:00Z"}),
        ("/slots/1/delete", {}),
    ]
    for path, data in writes:
        resp = cand.post(path, data)
        assert resp.status_code == 403, f"POST {path} -> {resp.status_code}"


# --------------------------------------------------------------------------
# Foreign owners: 403 (object exists, caller not allowed)
# --------------------------------------------------------------------------


def test_foreign_employer_cannot_manage_others_job(app, scene):
    ben = _login(app, "ben@test.local", "Password123!")
    backend = scene["jobs"]["backend"]  # owned by ana
    assert ben.get(f"/jobs/{backend}/edit").status_code == 403
    assert ben.get(f"/jobs/{backend}/applicants").status_code == 403
    assert ben.post(f"/jobs/{backend}/edit", {"title": "x", "description": "y", "skills": ""}).status_code == 403
    assert ben.post(f"/jobs/{backend}/delete", {}).status_code == 403


def test_foreign_candidate_cannot_touch_others_application_or_resume(app, scene):
    ids = scene
    app_id = ids["applications"]["alice_backend"]

    bob = _login(app, "bob@test.local", "Password123!")
    assert bob.get(f"/applications/{app_id}").status_code == 403
    assert bob.get(f"/candidates/{ids['users']['alice']}/resume").status_code == 403
    assert bob.post(f"/candidates/{ids['users']['alice']}/resume", {"resume_text": "hacked"}).status_code == 403
    # Booking with someone else's application (FP-SEC-1 boundary 3).
    assert bob.post("/bookings", {"application_id": app_id, "slot_id": 1}).status_code == 403

    # The job's owning employer may read the application detail...
    ana = _login(app, "ana@test.local", "Password123!")
    assert ana.get(f"/applications/{app_id}").status_code == 200
    # ...but a foreign employer cannot change its status.
    ben = _login(app, "ben@test.local", "Password123!")
    resp = ben.post(f"/applications/{app_id}/status", {"status": "Rejected", "job_id": ids["jobs"]["backend"]})
    assert resp.status_code == 403


# --------------------------------------------------------------------------
# Missing objects the caller would otherwise reach: 404
# --------------------------------------------------------------------------


def test_missing_objects_return_404(app, scene):
    alice = _login(app, "alice@test.local", "Password123!")
    assert alice.get("/applications/99999").status_code == 404
    assert alice.get("/jobs/99999").status_code == 404
    assert alice.get("/candidates/99999/resume").status_code == 404

    ana = _login(app, "ana@test.local", "Password123!")
    assert ana.get("/jobs/99999/edit").status_code == 404
    assert ana.get("/jobs/99999/applicants").status_code == 404
    assert ana.post("/jobs/99999/delete", {}).status_code == 404
    assert ana.post("/applications/99999/status", {"status": "Pending", "job_id": 1}).status_code == 404
    assert ana.post("/slots/99999/delete", {}).status_code == 404
