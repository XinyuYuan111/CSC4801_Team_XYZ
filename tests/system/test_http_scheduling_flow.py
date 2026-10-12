"""System: interview scheduling rules observed over HTTP (FP-SCHED-1..3).

Booking eligibility, availability visibility, conflict outcomes, and the
post-booking state of both parties — all asserted through rendered pages and
HTTP status codes only.
"""

import re

from tests.system.conftest import Browser


def _text(resp) -> str:
    return resp.get_data(as_text=True)


def _scenario(app):
    """One employer, two candidates, one job, one slot; Jo is Interviewing."""
    emp = Browser(app)
    jo = Browser(app)
    kim = Browser(app)
    assert emp.register("emp@sched.test", "Password123!", "Employer", company_name="Acme").status_code == 302
    assert jo.register("jo@sched.test", "Password123!", "Candidate", display_name="Jo Lin").status_code == 302
    assert kim.register("kim@sched.test", "Password123!", "Candidate", display_name="Kim Oak").status_code == 302
    assert emp.post("/company", {"company_name": "Acme", "description": "d"}).status_code == 302
    assert emp.post(
        "/employer/jobs/new", {"title": "Backend", "description": "d", "skills": "Python"}
    ).status_code == 302
    assert emp.post("/employer/slots", {"job_id": 1, "start_utc": "2031-06-01T15:00:00Z"}).status_code == 302

    for cand, name in ((jo, "Jo Lin"), (kim, "Kim Oak")):
        assert cand.post("/profile", {"display_name": name, "skills": "Python"}).status_code == 302
        assert cand.get("/jobs/1").status_code == 200
        assert cand.post("/jobs/1/apply", {}).status_code == 302

    slot_match = re.search(r"/slots/(\d+)/delete", _text(emp.get("/employer/slots")))
    assert slot_match, "seeded slot must appear on the employer slots page"
    slot_id = slot_match.group(1)

    html = _text(emp.get("/jobs/1/applicants"))
    apps = re.findall(r"/applications/(\d+)/status", html)
    assert len(apps) == 2, html
    assert emp.post(f"/applications/{apps[0]}/status", {"status": "Interviewing", "job_id": 1}).status_code == 302
    return emp, jo, kim, apps, slot_id


def test_slot_rejects_invalid_times_over_http(app):
    emp = Browser(app)
    assert emp.register("e@t.test", "Password123!", "Employer", company_name="C").status_code == 302
    assert emp.post("/employer/jobs/new", {"title": "J", "description": "d", "skills": ""}).status_code == 302

    # Past slot.
    resp = emp.post("/employer/slots", {"job_id": 1, "start_utc": "2020-01-01T15:00:00Z"})
    assert resp.status_code == 400
    # Garbage time.
    resp = emp.post("/employer/slots", {"job_id": 1, "start_utc": "not-a-time"})
    assert resp.status_code == 400
    # Missing job selection.
    resp = emp.post("/employer/slots", {"start_utc": "2031-06-01T15:00:00Z"})
    assert resp.status_code == 400
    # Foreign job id (tampered form) must not create a slot on someone else's job.
    other = Browser(app)
    assert other.register("e2@t.test", "Password123!", "Employer", company_name="D").status_code == 302
    assert other.post("/employer/jobs/new", {"title": "J2", "description": "d", "skills": ""}).status_code == 302
    resp = emp.post("/employer/slots", {"job_id": 2, "start_utc": "2031-06-01T15:00:00Z"})
    assert resp.status_code == 403
    # A valid slot is exactly 30 minutes (server computes end = start + 30m).
    assert emp.post("/employer/slots", {"job_id": 1, "start_utc": "2031-06-01T15:00:00Z"}).status_code == 302
    slots_html = _text(emp.get("/employer/slots"))
    assert "15:00" in slots_html and "15:30" in slots_html


def test_booking_eligibility_rules_over_http(app):
    emp, jo, kim, apps, slot_id = _scenario(app)
    jo_app, kim_app = apps  # sorted: both score 100, Jo Lin before Kim Oak

    # Kim is still Pending: no booking UI, and direct POST fails cleanly.
    kim_html = _text(kim.get(f"/applications/{kim_app}"))
    assert "Book an interview slot" not in kim_html
    resp = kim.post("/bookings", {"application_id": kim_app, "slot_id": slot_id})
    assert resp.status_code == 409
    assert "Interviewing" in _text(resp) or "not in Interviewing" in _text(resp)

    # Jo is Interviewing: the slot is offered and booking succeeds.
    jo_html = _text(jo.get(f"/applications/{jo_app}"))
    assert "Book an interview slot" in jo_html
    assert "2031-06-01" in jo_html
    resp = jo.post("/bookings", {"application_id": jo_app, "slot_id": slot_id})
    assert resp.status_code == 302

    # The booked slot is no longer offered to Kim (even after she becomes Interviewing).
    assert emp.post(f"/applications/{kim_app}/status", {"status": "Interviewing", "job_id": 1}).status_code == 302
    kim_html = _text(kim.get(f"/applications/{kim_app}"))
    assert "Book an interview slot" in kim_html  # eligible...
    assert 'name="slot_id"' not in kim_html  # ...but no bookable slot remains
    assert "No available slots right now" in kim_html

    # Jo already has a booking: no second booking UI, and a forged POST fails.
    jo_html = _text(jo.get(f"/applications/{jo_app}"))
    assert "Book an interview slot" not in jo_html
    resp = jo.post("/bookings", {"application_id": jo_app, "slot_id": slot_id})
    assert resp.status_code == 409


def test_conflict_message_is_the_documented_one(app):
    emp, jo, kim, apps, slot_id = _scenario(app)
    jo_app, kim_app = apps
    assert emp.post(f"/applications/{kim_app}/status", {"status": "Interviewing", "job_id": 1}).status_code == 302
    assert jo.post("/bookings", {"application_id": jo_app, "slot_id": slot_id}).status_code == 302
    resp = kim.post("/bookings", {"application_id": kim_app, "slot_id": slot_id})
    assert resp.status_code == 409
    assert "Slot already booked" in _text(resp), _text(resp)


def test_booking_survives_status_change_and_slot_stays_unavailable(app):
    emp, jo, kim, apps, slot_id = _scenario(app)
    jo_app, _ = apps
    assert jo.post("/bookings", {"application_id": jo_app, "slot_id": slot_id}).status_code == 302

    # Employer moves Jo out of Interviewing; booking stays, slot stays locked.
    assert emp.post(f"/applications/{jo_app}/status", {"status": "Accepted", "job_id": 1}).status_code == 302
    detail = _text(jo.get(f"/applications/{jo_app}"))
    assert "Interview booking" in detail
    slots_html = _text(emp.get("/employer/slots"))
    assert re.search(r"2031-06-01", slots_html)
    # Employer slot list must show it as not available.
    row_html = slots_html.split("2031-06-01")[1][:400]
    assert "booked" in row_html.lower() or "Unavailable" in row_html or "available" not in row_html.lower()

    # Deleting the booked slot is refused; deleting the job is refused.
    assert emp.post(f"/slots/{slot_id}/delete", {}).status_code == 409
    assert emp.post("/jobs/1/delete", {}).status_code == 409


def test_employer_slot_delete_only_own_and_unbooked(app):
    emp, jo, kim, apps, slot_id = _scenario(app)
    other = Browser(app)
    assert other.register("x@t.test", "Password123!", "Employer", company_name="X").status_code == 302
    assert other.post(f"/slots/{slot_id}/delete", {}).status_code == 403

    # Unbooked slot of the owner can be deleted; a second time it is 404.
    assert emp.post(f"/slots/{slot_id}/delete", {}).status_code == 302
    assert emp.post(f"/slots/{slot_id}/delete", {}).status_code == 404
