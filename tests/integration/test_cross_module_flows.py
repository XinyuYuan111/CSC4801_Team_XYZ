"""Integration: multi-module workflows (services + matching + schema together).

Covers consistency guarantees that only appear when several components interact:
the same match score on candidate and employer views, booking persistence across
status changes, and skill edits recomputing scores everywhere.
"""

import pytest

from app.errors import AuthorizationError, ConflictError
from app.matching import match_score
from app.services import applications as applications_service
from app.services import jobs as jobs_service
from app.services import profiles as profiles_service
from app.services import scheduling as scheduling_service


def test_candidate_and_employer_views_share_one_match_implementation(db, world):
    """FP-MATCH-1: both sides must call the same scoring function — compare outputs."""
    ids = world(include_cara=True)
    applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"])
    applications_service.apply_to_job(ids["users"]["bob"], ids["jobs"]["backend"])
    applications_service.apply_to_job(ids["users"]["cara"], ids["jobs"]["backend"])

    dashboard = jobs_service.list_jobs_with_scores(ids["users"]["alice"])
    alice_row = next(r for r in dashboard if r["job_id"] == ids["jobs"]["backend"])
    assert alice_row["score"] == match_score(["python", "sql"], ["python", "sql"]) == 100

    applicants = applications_service.list_applicants(ids["users"]["ana"], ids["jobs"]["backend"])
    by_name = {row["display_name"]: row for row in applicants}
    assert by_name["Alice Chen"]["score"] == 100
    assert by_name["Bob Patel"]["score"] == match_score(["python"], ["python", "sql"]) == 50
    assert by_name["Cara Diaz"]["score"] == match_score(["rust"], ["python", "sql"]) == 0

    # The zero/50/100 rows must be ordered by descending score on the employer side.
    assert [row["score"] for row in applicants] == [100, 50, 0]


def test_empty_required_skills_scores_100_for_any_candidate(db, world):
    ids = world()
    applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["analyst"])
    dashboard = jobs_service.list_jobs_with_scores(ids["users"]["alice"])
    analyst = next(r for r in dashboard if r["job_id"] == ids["jobs"]["analyst"])
    assert analyst["score"] == 100
    applicants = applications_service.list_applicants(ids["users"]["ben"], ids["jobs"]["analyst"])
    assert applicants[0]["score"] == 100


def test_skill_edit_recomputes_scores_on_both_views(db, world):
    ids = world()
    applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"])
    assert applications_service.list_applicants(ids["users"]["ana"], ids["jobs"]["backend"])[0]["score"] == 100

    # Employer widens the required skills; Alice keeps python, sql.
    jobs_service.update_job(ids["users"]["ana"], ids["jobs"]["backend"], "Backend Engineer", "APIs.", "Python, SQL, Rust")
    applicants = applications_service.list_applicants(ids["users"]["ana"], ids["jobs"]["backend"])
    assert applicants[0]["score"] == match_score(["python", "sql"], ["python", "sql", "rust"]) == 66

    # Candidate edits skills; both views must follow without any manual refresh.
    profiles_service.update_candidate_profile(ids["users"]["alice"], "Alice Chen", "Python, SQL, Rust")
    applicants = applications_service.list_applicants(ids["users"]["ana"], ids["jobs"]["backend"])
    dashboard = jobs_service.list_jobs_with_scores(ids["users"]["alice"])
    job_row = next(r for r in dashboard if r["job_id"] == ids["jobs"]["backend"])
    assert applicants[0]["score"] == 100 == job_row["score"]


def test_booking_is_visible_to_both_sides_and_survives_status_change(db, world):
    ids = world()
    app_id = applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"])
    applications_service.set_status(ids["users"]["ana"], app_id, "Interviewing")
    slot_id = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-01T15:00:00Z", "2030-05-01T15:30:00Z"
    )
    scheduling_service.book_slot(ids["users"]["alice"], app_id, slot_id)

    candidate_view = applications_service.get_application_for_candidate(ids["users"]["alice"], app_id)
    employer_view = applications_service.get_application_for_employer(ids["users"]["ana"], app_id)
    assert candidate_view["booking"] == employer_view["booking"]
    assert candidate_view["booking"]["slot_id"] == slot_id

    # Leaving Interviewing keeps the booking linked and the slot unavailable.
    applications_service.set_status(ids["users"]["ana"], app_id, "Rejected")
    candidate_view = applications_service.get_application_for_candidate(ids["users"]["alice"], app_id)
    assert candidate_view["booking"] is not None
    assert scheduling_service.list_available_slots(ids["users"]["ana"]) == []
    employer_slots = scheduling_service.list_slots_for_employer(ids["users"]["ana"])
    assert all(s["available"] is False for s in employer_slots)

    # The application still cannot take a second booking.
    slot2 = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-02T15:00:00Z", "2030-05-02T15:30:00Z"
    )
    applications_service.set_status(ids["users"]["ana"], app_id, "Interviewing")
    with pytest.raises(ConflictError) as excinfo:
        scheduling_service.book_slot(ids["users"]["alice"], app_id, slot2)
    assert excinfo.value.message == "Application already has a booking"


def test_unbooked_slot_disappears_from_availability_only_when_booked(db, world):
    ids = world()
    app_a, app_b = (
        applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"]),
        applications_service.apply_to_job(ids["users"]["bob"], ids["jobs"]["backend"]),
    )
    for app_id in (app_a, app_b):
        applications_service.set_status(ids["users"]["ana"], app_id, "Interviewing")
    slot_id = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], "2030-05-01T15:00:00Z", "2030-05-01T15:30:00Z"
    )
    listed = scheduling_service.list_available_slots(ids["users"]["ana"])
    assert [s["slot_id"] for s in listed] == [slot_id]
    scheduling_service.book_slot(ids["users"]["alice"], app_a, slot_id)
    assert scheduling_service.list_available_slots(ids["users"]["ana"]) == []


def test_tie_breaking_stable_across_dashboard_and_applicants(db, world):
    """Scores equal: titles/names break ties case-insensitively, then stable id."""
    ids = world(include_cara=True)
    # Two jobs with the same (empty) required skills so every candidate scores 100.
    j1 = jobs_service.create_job(ids["users"]["ana"], "alpha role", "d", "")
    j2 = jobs_service.create_job(ids["users"]["ana"], "Beta Role", "d", "")
    for job_id in (j1, j2):
        for cand in ("alice", "bob", "cara"):
            applications_service.apply_to_job(ids["users"][cand], job_id)

    dashboard = jobs_service.list_jobs_with_scores(ids["users"]["alice"])
    empty_skill_jobs = [r["title"] for r in dashboard if r["job_id"] in (j1, j2)]
    assert empty_skill_jobs == ["alpha role", "Beta Role"]  # case-insensitive title order

    applicants = applications_service.list_applicants(ids["users"]["ana"], j1)
    names = [r["display_name"] for r in applicants]
    assert names == ["Alice Chen", "Bob Patel", "Cara Diaz"]  # display-name order


def test_cross_job_slot_booking_matches_employer_contract(db, world):
    """FP-SCHED-2 allows a different reference job under the same employer."""
    ids = world()
    other_job = jobs_service.create_job(ids["users"]["ana"], "Second Job", "d", "Python")
    app_backend = applications_service.apply_to_job(ids["users"]["alice"], ids["jobs"]["backend"])
    applications_service.set_status(ids["users"]["ana"], app_backend, "Interviewing")
    slot_other = scheduling_service.create_slot(
        ids["users"]["ana"], other_job, "2030-05-01T15:00:00Z", "2030-05-01T15:30:00Z"
    )

    assert slot_other in [s["slot_id"] for s in scheduling_service.list_available_slots(ids["users"]["ana"])]
    booking_id = scheduling_service.book_slot(ids["users"]["alice"], app_backend, slot_other)
    for detail in (
        applications_service.get_application_for_candidate(ids["users"]["alice"], app_backend),
        applications_service.get_application_for_employer(ids["users"]["ana"], app_backend),
    ):
        assert detail["job_id"] == ids["jobs"]["backend"]
        assert detail["booking"]["booking_id"] == booking_id
        assert detail["booking"]["slot_id"] == slot_other
    assert scheduling_service.list_available_slots(ids["users"]["ana"]) == []
