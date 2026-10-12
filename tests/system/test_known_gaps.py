"""System regressions for the status redirect findings in REVIEW.md."""

import re

import pytest

from tests.system.conftest import Browser


@pytest.fixture()
def hire_scene(app):
    """Employer ana owns job 1 with Alice's application; employer ben owns job 2."""
    ana, ben, alice = Browser(app), Browser(app), Browser(app)
    assert ana.register("ana@gap.test", "Password123!", "Employer", company_name="Acme").status_code == 302
    assert ben.register("ben@gap.test", "Password123!", "Employer", company_name="Globex").status_code == 302
    assert alice.register("al@gap.test", "Password123!", "Candidate", display_name="Al").status_code == 302
    assert ana.post("/employer/jobs/new", {"title": "JobA", "description": "d", "skills": "Python"}).status_code == 302
    assert ben.post("/employer/jobs/new", {"title": "JobB", "description": "d", "skills": "Python"}).status_code == 302
    assert alice.post("/jobs/1/apply", {}).status_code == 302
    apps = re.findall(r"/applications/(\d+)/status", _text(ana.get("/jobs/1/applicants")))
    assert len(apps) == 1
    return ana, ben, int(apps[0])


def _text(resp) -> str:
    return resp.get_data(as_text=True)


def test_status_change_redirects_to_the_applications_own_job(hire_scene):
    """Ignore tampered job_id; redirect to the application's stored job."""
    ana, ben, app_id = hire_scene
    resp = ana.post(f"/applications/{app_id}/status", {"status": "Interviewing", "job_id": 2})
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"/jobs/1/applicants", resp.headers["Location"]
    # And following it must be a success page, not an error page.
    followed = ana.get(resp.headers["Location"])
    assert followed.status_code == 200


def test_status_change_does_not_require_redundant_job_id(hire_scene):
    """The application ID already identifies the destination job."""
    ana, ben, app_id = hire_scene
    resp = ana.post(f"/applications/{app_id}/status", {"status": "Interviewing"})
    assert resp.status_code == 302
    assert resp.headers["Location"] == "/jobs/1/applicants"
    assert ana.get(resp.headers["Location"]).status_code == 200
