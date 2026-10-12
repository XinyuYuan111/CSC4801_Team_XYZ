"""System: multi-role HTTP journeys through the real UI flow.

Each test follows what a user actually does in a browser — open form, submit
form (CSRF scraped from the page), follow redirects — and asserts on the
rendered HTML. No service-layer calls: setup and verification are all HTTP.
"""

import re

from tests.system.conftest import Browser


def _text(resp) -> str:
    return resp.get_data(as_text=True)


def test_candidate_full_journey_over_http(app):
    b = Browser(app)
    # Register a brand-new candidate.
    resp = b.register(
        "cara@e2e.test", "Password123!", "Candidate", display_name="Cara Diaz"
    )
    assert resp.status_code == 302
    assert "/dashboard" in resp.headers["Location"]

    # Empty dashboard (no jobs yet).
    resp = b.get("/dashboard")
    assert resp.status_code == 200
    assert "No jobs posted yet" in _text(resp)

    # Profile: set skills (FP-CAN-1).
    resp = b.get("/profile")
    assert resp.status_code == 200
    resp = b.post("/profile", {"display_name": "Cara Diaz", "skills": " Rust ,  Go , rust "})
    assert resp.status_code == 302

    # Resume: replace and read back (FP-CAN-1). The profile page links to the
    # owner's resume; extract the id from there rather than guessing.
    profile_html = _text(b.get("/profile"))
    match = re.search(r'/candidates/(\d+)/resume', profile_html)
    assert match, "profile page must link to the owner's resume"
    cand_id = match.group(1)
    resp = b.get(f"/candidates/{cand_id}/resume")
    assert resp.status_code == 200
    resp = b.post(f"/candidates/{cand_id}/resume", {"resume_text": "Systems programmer focused on Rust."})
    assert resp.status_code == 302
    assert "Systems programmer" in _text(b.get(f"/candidates/{cand_id}/resume"))

    # Logout must actually end the session.
    resp = b.logout()
    assert resp.status_code == 302
    resp = b.get("/dashboard")
    assert resp.status_code == 302 and "/login" in resp.headers["Location"]


def test_two_candidates_and_employer_hire_and_book_journey(app):
    cand1, cand2, emp = Browser(app), Browser(app), Browser(app)

    assert cand1.register("j1@e2e.test", "Password123!", "Candidate", display_name="Jo Lin").status_code == 302
    assert cand2.register("k2@e2e.test", "Password123!", "Candidate", display_name="Kim Oak").status_code == 302
    assert emp.register("hr@e2e.test", "Password123!", "Employer", company_name="Acme").status_code == 302

    # Employer creates company + job.
    assert emp.get("/company").status_code == 200
    assert emp.post("/company", {"company_name": "Acme", "description": "Widgets."}).status_code == 302
    assert emp.get("/employer/jobs/new").status_code == 200
    resp = emp.post(
        "/employer/jobs/new",
        {"title": "Backend Engineer", "description": "APIs in Python.", "skills": "Python, SQL"},
    )
    assert resp.status_code == 302

    jobs_html = _text(emp.get("/employer/jobs"))
    job_link = re.search(r"/jobs/(\d+)/edit", jobs_html)
    assert job_link, "employer jobs page must link to the edit form"
    job_id = job_link.group(1)

    # Employer adds one future slot.
    resp = emp.post("/employer/slots", {"job_id": job_id, "start_utc": "2031-05-01T15:00:00Z"})
    assert resp.status_code == 302
    slots_html = _text(emp.get("/employer/slots"))
    slot_link = re.search(r"/slots/(\d+)/delete", slots_html)
    assert slot_link, "slots page must offer slot deletion"
    slot_id = slot_link.group(1)

    # Both candidates see the job with scores (100 vs 50: exact vs partial skills).
    assert cand1.post("/profile", {"display_name": "Jo Lin", "skills": "Python, SQL"}).status_code == 302
    assert cand2.post("/profile", {"display_name": "Kim Oak", "skills": "Python"}).status_code == 302
    dash1 = _text(cand1.get("/dashboard"))
    dash2 = _text(cand2.get("/dashboard"))
    assert "Backend Engineer" in dash1 and "Acme" in dash1
    # score column precedes the title cell in each row
    assert re.search(r'<td class="score">100</td>\s*<td>Backend Engineer</td>', dash1), dash1
    assert re.search(r'<td class="score">50</td>\s*<td>Backend Engineer</td>', dash2), dash2

    # Both apply (FP-CAN-3); duplicate apply is rejected.
    assert cand1.get(f"/jobs/{job_id}").status_code == 200
    assert cand1.post(f"/jobs/{job_id}/apply", {}).status_code == 302
    resp = cand1.post(f"/jobs/{job_id}/apply", {})
    assert resp.status_code == 409
    assert cand2.post(f"/jobs/{job_id}/apply", {}).status_code == 302

    # Employer sees applicants sorted by score: Jo (100) before Kim (50).
    applicants_html = _text(emp.get(f"/jobs/{job_id}/applicants"))
    assert applicants_html.index("Jo Lin") < applicants_html.index("Kim Oak")

    # Status transitions: Jo -> Interviewing.
    app_links = re.findall(r"/applications/(\d+)/status", applicants_html)
    assert len(app_links) == 2
    # The first status form in the table is Jo's (sorted by score).
    resp = emp.post(f"/applications/{app_links[0]}/status", {"status": "Interviewing", "job_id": job_id})
    assert resp.status_code == 302

    # Jo books the slot from the application detail page.
    detail_html = _text(cand1.get(f"/applications/{app_links[0]}"))
    assert "Interviewing" in detail_html
    assert "2031-05-01" in detail_html  # slot offered in the booking table
    resp = cand1.post("/bookings", {"application_id": app_links[0], "slot_id": slot_id})
    assert resp.status_code == 302

    # Both sides now see the booking; the slot is gone from availability.
    detail_html = _text(cand1.get(f"/applications/{app_links[0]}"))
    assert "Interview booking" in detail_html and "15:00" in detail_html
    applicants_html = _text(emp.get(f"/jobs/{job_id}/applicants"))
    assert "2031-05-01" in applicants_html

    # Kim (still Pending) cannot book; the slot is not even offered.
    kim_detail = re.search(r"/applications/(\d+)", _text(cand2.get("/applications")))
    kim_app = re.search(r"/applications/(\d+)/status", applicants_html)
    # Kim's application id is the second form on the applicants page.
    kim_app_id = app_links[1]
    kim_html = _text(cand2.get(f"/applications/{kim_app_id}"))
    assert "Book an interview slot" not in kim_html
    resp = cand2.post("/bookings", {"application_id": kim_app_id, "slot_id": slot_id})
    assert resp.status_code in (403, 409)  # not Interviewing and/or already booked

    # Booked slot cannot be deleted; job with applications cannot be deleted.
    assert emp.post(f"/slots/{slot_id}/delete", {}).status_code == 409
    assert emp.post(f"/jobs/{job_id}/delete", {}).status_code == 409


def test_dashboard_ranks_all_jobs_and_links_descriptions(app):
    cand, emp = Browser(app), Browser(app)
    assert emp.register("e@e2e.test", "Password123!", "Employer", company_name="Globex").status_code == 302
    assert cand.register("c@e2e.test", "Password123!", "Candidate", display_name="Cal").status_code == 302
    assert cand.post("/profile", {"display_name": "Cal", "skills": "Python"}).status_code == 302

    for title, skills in (("ZZZ Low", "Rust"), ("AAA High", "Python"), ("MMM Mid", "Python, SQL")):
        resp = emp.post("/employer/jobs/new", {"title": title, "description": "d", "skills": skills})
        assert resp.status_code == 302

    html = _text(cand.get("/dashboard"))
    # Scores: AAA High 100, MMM Mid 50, ZZZ Low 0 — descending.
    order = re.findall(r'<td class="score">(\d+)</td>\s*<td>([^<]+)</td>', html)
    assert order == [("100", "AAA High"), ("50", "MMM Mid"), ("0", "ZZZ Low")], order
    # Every row offers a way to view the description (FP-CAN-2).
    assert html.count("View description") == 3
