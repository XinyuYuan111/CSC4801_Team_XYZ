"""Unit tests for FP-CAN-1..3 and FP-EMP-1..3: candidate and employer workflows."""

import pytest

from app.errors import AuthorizationError, ConflictError, NotFoundError, ValidationError
from app.services import applications as applications_service
from app.services import jobs as jobs_service
from app.services import profiles as profiles_service
from app.services import scheduling as scheduling_service
from tests.conftest import make_future_slot_start, make_slot_end


def test_fp_can_1_profile_and_private_resume_rules(client, app, world):
    ids = world(include_cara=True)
    alice, cara = ids["users"]["alice"], ids["users"]["cara"]

    with app.app_context():
        # Alice can view and edit only her own profile (skills reach the matcher).
        profile = profiles_service.get_candidate_profile(alice)
        assert profile["display_name"] == "Alice Chen"
        updated = profiles_service.update_candidate_profile(
            alice, "Alice C.", "  Python ,  python ,  SQL  "
        )
        assert updated["display_name"] == "Alice C."
        assert updated["skills"] == ["python", "sql"]  # normalized and deduplicated

        # Skills are available to the matching function.
        from app.matching import match_score

        assert match_score(updated["skills"], ["python", "sql"]) == 100

        # Resume: the owner can enter, view, and replace raw text.
        profiles_service.replace_resume(alice, alice, "First resume text")
        assert profiles_service.read_resume(alice, alice) == "First resume text"
        profiles_service.replace_resume(alice, alice, "Second resume text")
        assert profiles_service.read_resume(alice, alice) == "Second resume text"

        # Other candidates and employers receive 403 on direct access (FP-CAN-1).
        with pytest.raises(AuthorizationError):
            profiles_service.read_resume(cara, alice)
        with pytest.raises(AuthorizationError):
            profiles_service.replace_resume(cara, alice, "stolen")
        with pytest.raises(AuthorizationError):
            profiles_service.read_resume(ids["users"]["ana"], alice)
        assert profiles_service.read_resume(alice, alice) == "Second resume text"  # unchanged

    # The HTTP direct-URL contract matches (403 for others).
    client.login("cara@test.local", "Password123!")
    response = client.get(f"/candidates/{alice}/resume")
    assert response.status_code == 403
    response = client.post(f"/candidates/{alice}/resume", data={"resume_text": "stolen"})
    assert response.status_code == 403
    client.logout()
    client.login("ana@test.local", "Password123!")
    assert client.get(f"/candidates/{alice}/resume").status_code == 403


def test_fp_can_2_recommendations_preserve_fields_and_rank_all_jobs(client, app, world):
    ids = world()
    alice = ids["users"]["alice"]

    with app.app_context():
        # Give Alice mixed skills so both jobs get real scores: 100 and 50+.
        profiles_service.update_candidate_profile(alice, "Alice Chen", "Python")
        rows = jobs_service.list_jobs_with_scores(alice)

    # All current (not deleted) jobs are listed with required fields.
    job_ids = {row["job_id"] for row in rows}
    assert ids["jobs"]["backend"] in job_ids
    assert ids["jobs"]["analyst"] in job_ids
    for row in rows:
        assert row["title"]
        assert "company_name" in row
        assert "required_skills" in row
        assert "description" in row
        assert 0 <= row["score"] <= 100

    # Sorted from highest to lowest score (backend: python of {python,sql} = 50;
    # analyst: empty required = 100).
    scores = [row["score"] for row in rows]
    assert scores == sorted(scores, reverse=True)
    by_id = {row["job_id"]: row for row in rows}
    assert by_id[ids["jobs"]["analyst"]]["score"] == 100
    assert by_id[ids["jobs"]["backend"]]["score"] == 50

    # The dashboard shows title, employer/company, required skills, and a way
    # to view the description.
    client.login("alice@test.local", "Password123!")
    page = client.get("/dashboard")
    assert page.status_code == 200
    assert b"Backend Engineer" in page.data
    assert b"Acme Corp" in page.data
    assert b"python" in page.data
    assert b"View description" in page.data
    detail = client.get(f"/jobs/{ids['jobs']['backend']}")
    assert detail.status_code == 200
    assert b"APIs in Python." in detail.data


def test_fp_can_3_pending_duplicate_and_application_owner(client, app, world):
    ids = world()
    alice, bob = ids["users"]["alice"], ids["users"]["bob"]
    backend = ids["jobs"]["backend"]

    # Apply through the HTTP surface first: a new application starts Pending.
    client.login("alice@test.local", "Password123!")
    response = client.post(f"/jobs/{backend}/apply")
    assert response.status_code == 302

    with app.app_context():
        rows = applications_service.list_my_applications(alice)
        assert len(rows) == 1
        app_id = rows[0]["application_id"]
        detail = applications_service.get_application_for_candidate(alice, app_id)
        assert detail["status"] == "Pending"
        assert detail["title"] == "Backend Engineer"
        assert detail["company_name"] == "Acme Corp"
        assert detail["booking"] is None

        # A duplicate application is rejected without creating another row,
        # with the documented conflict message (constraint-backed, race-safe).
        with pytest.raises(ConflictError) as excinfo:
            applications_service.apply_to_job(alice, backend)
        assert excinfo.value.message == "Application already submitted"
        assert len(applications_service.list_my_applications(alice)) == 1

        # A candidate cannot view another candidate's application (FP-CAN-3).
        with pytest.raises(AuthorizationError):
            applications_service.get_application_for_candidate(bob, app_id)

        # A candidate cannot change an application status.
        with pytest.raises(AuthorizationError):
            applications_service.set_status(alice, app_id, "Accepted")

    # Duplicate apply over HTTP: 409, still one row. Status change: 403.
    assert client.post(f"/jobs/{backend}/apply").status_code == 409
    assert client.post(
        f"/applications/{app_id}/status",
        data={"status": "Accepted", "job_id": backend},
    ).status_code == 403

    # Own application view shows job, employer, status, and booking (if any).
    page = client.get(f"/applications/{app_id}")
    assert page.status_code == 200
    assert b"Backend Engineer" in page.data
    assert b"Acme Corp" in page.data
    assert b"Pending" in page.data

    # Another candidate's application is 403 via direct URL.
    client.logout()
    client.login("bob@test.local", "Password123!")
    assert client.get(f"/applications/{app_id}").status_code == 403


def test_fp_emp_1_company_profile(client, app, world):
    ids = world()
    ana = ids["users"]["ana"]

    with app.app_context():
        company = profiles_service.get_company(ana)
        assert company["company_name"] == "Acme Corp"
        updated = profiles_service.update_company(ana, "Acme Corporation", "We build infrastructure.")
        assert updated["company_name"] == "Acme Corporation"
        assert updated["description"] == "We build infrastructure."
        with pytest.raises(ValidationError):
            profiles_service.update_company(ana, "   ", "No name")

    client.login("ana@test.local", "Password123!")
    page = client.get("/company")
    assert page.status_code == 200
    assert b"Acme Corporation" in page.data
    response = client.post(
        "/company", data={"company_name": "Acme Corp", "description": "Updated description."}
    )
    assert response.status_code == 302
    page = client.get("/company")
    assert b"Updated description." in page.data


def test_fp_emp_2_job_validation_and_deletion(client, app, world):
    ids = world()
    ana, ben, alice = ids["users"]["ana"], ids["users"]["ben"], ids["users"]["alice"]
    backend = ids["jobs"]["backend"]

    with app.app_context():
        # Title and description are required; empty skills are allowed.
        with pytest.raises(ValidationError):
            jobs_service.create_job(ana, "", "Desc", "Python")
        with pytest.raises(ValidationError):
            jobs_service.create_job(ana, "Title", "  ", "Python")
        job_id = jobs_service.create_job(ana, "DevOps Engineer", "Pipelines.", "")
        job = jobs_service.get_job(job_id)
        assert job["required_skills"] == []

        # Another employer cannot edit, delete, or manage applicants (403) —
        # including GET of the edit form, not only the POST (FP-EMP-2).
        with pytest.raises(AuthorizationError):
            jobs_service.get_owned_job(ben, job_id)
        with pytest.raises(AuthorizationError):
            jobs_service.update_job(ben, job_id, "Hijack", "Hijack", "")
        with pytest.raises(AuthorizationError):
            jobs_service.delete_job(ben, job_id)
        with pytest.raises(AuthorizationError):
            applications_service.list_applicants(ben, job_id)

        # A job with no applications and no interview slots is deletable.
        jobs_service.delete_job(ana, job_id)
        with pytest.raises(NotFoundError):
            jobs_service.get_job(job_id)

        # A job with an application cannot be deleted: 409, everything unchanged.
        applications_service.apply_to_job(alice, backend)
        with pytest.raises(ConflictError) as excinfo:
            jobs_service.delete_job(ana, backend)
        assert excinfo.value.status == 409
        assert jobs_service.get_job(backend)["title"] == "Backend Engineer"
        assert len(applications_service.list_applicants(ana, backend)) == 1

        # DB-level backstop (P6): ON DELETE RESTRICT refuses the raw delete too,
        # so dependents can never be silently cascade-removed.
        import sqlite3

        from app.db import get_db, transaction

        with pytest.raises(sqlite3.IntegrityError):
            with transaction():
                get_db().execute("DELETE FROM jobs WHERE id = ?", (backend,))
        assert jobs_service.get_job(backend)["title"] == "Backend Engineer"

        # A job with an interview slot (even unbooked) cannot be deleted: 409.
        fresh = jobs_service.create_job(ana, "SRE", "Reliability.", "Linux")
        start = make_future_slot_start()
        scheduling_service.create_slot(ana, fresh, start, make_slot_end(start))
        with pytest.raises(ConflictError):
            jobs_service.delete_job(ana, fresh)
        assert jobs_service.get_job(fresh)["title"] == "SRE"

    # HTTP surface for delete conflicts and cross-employer access.
    client.login("ana@test.local", "Password123!")
    response = client.post(f"/jobs/{backend}/delete")
    assert response.status_code == 409
    client.logout()
    client.login("ben@test.local", "Password123!")
    assert client.post(f"/jobs/{backend}/delete").status_code == 403
    assert client.post(
        f"/jobs/{backend}/edit", data={"title": "X", "description": "Y", "skills": ""}
    ).status_code == 403
    # GET of the edit form is also "attempting to edit": 403, content withheld.
    response = client.get(f"/jobs/{backend}/edit")
    assert response.status_code == 403
    assert b"APIs in Python." not in response.data


def test_fp_emp_3_applicant_fields_order_status_and_role(client, app, world):
    ids = world(include_cara=True)
    ana, ben = ids["users"]["ana"], ids["users"]["ben"]
    alice, bob, cara = ids["users"]["alice"], ids["users"]["bob"], ids["users"]["cara"]
    backend = ids["jobs"]["backend"]

    with app.app_context():
        alice_app = applications_service.apply_to_job(alice, backend)  # score 100
        bob_app = applications_service.apply_to_job(bob, backend)  # score 50
        cara_app = applications_service.apply_to_job(cara, backend)  # score 0

        rows = applications_service.list_applicants(ana, backend)
        # Sorted by match score from highest to lowest.
        assert [row["score"] for row in rows] == [100, 50, 0]
        assert [row["display_name"] for row in rows] == ["Alice Chen", "Bob Patel", "Cara Diaz"]

        # Each row shows candidate identity, skills, score, status, and booking.
        for row in rows:
            assert row["display_name"]
            assert isinstance(row["skills"], list)
            assert 0 <= row["score"] <= 100
            assert row["status"] == "Pending"
            assert row["booking"] is None

        # Tie-breaking: equal scores order by display name, then candidate id.
        # Bob (python) and a clone with the same skills and different names.
        profiles_service.update_candidate_profile(cara, "Cara Diaz", "Python, SQL")  # now 100
        rows = applications_service.list_applicants(ana, backend)
        assert [row["score"] for row in rows] == [100, 100, 50]
        assert [row["display_name"] for row in rows] == ["Alice Chen", "Cara Diaz", "Bob Patel"]

        # The owner sets any of the four statuses.
        for status in ("Interviewing", "Rejected", "Accepted", "Pending"):
            applications_service.set_status(ana, alice_app, status)
            detail = applications_service.get_application_for_employer(ana, alice_app)
            assert detail["status"] == status

        # Invalid status values are rejected.
        with pytest.raises(ValidationError):
            applications_service.set_status(ana, alice_app, "Hired")

        # Other employers and candidates cannot change status.
        with pytest.raises(AuthorizationError):
            applications_service.set_status(ben, alice_app, "Rejected")
        with pytest.raises(AuthorizationError):
            applications_service.set_status(alice, bob_app, "Accepted")

        # The owning employer can open the application detail (SPEC route table);
        # a foreign employer cannot (403) and a missing application is 404.
        detail = applications_service.get_application_for_employer(ana, alice_app)
        assert detail["status"] in ("Pending", "Interviewing", "Rejected", "Accepted")
        assert detail["title"] == "Backend Engineer"
        with pytest.raises(AuthorizationError):
            applications_service.get_application_for_employer(ben, alice_app)

        # Booking appears in the applicant row for the owning employer.
        start = make_future_slot_start()
        slot_id = scheduling_service.create_slot(ana, backend, start, make_slot_end(start))
        applications_service.set_status(ana, cara_app, "Interviewing")
        scheduling_service.book_slot(cara, cara_app, slot_id)
        rows = applications_service.list_applicants(ana, backend)
        cara_row = next(r for r in rows if r["candidate_id"] == cara)
        assert cara_row["booking"] is not None
        assert cara_row["booking"]["slot_id"] == slot_id

    # HTTP surface: the applicants page shows the fields and status controls.
    client.login("ana@test.local", "Password123!")
    page = client.get(f"/jobs/{backend}/applicants")
    assert page.status_code == 200
    assert b"Alice Chen" in page.data
    assert b"python" in page.data
    assert b"Interviewing" in page.data
    # The owning employer can read one application's detail page (P3/SPEC).
    response = client.get(f"/applications/{alice_app}")
    assert response.status_code == 200
    assert b"Backend Engineer" in response.data
    # Other employer cannot read the applicant list or the application detail (403).
    client.logout()
    client.login("ben@test.local", "Password123!")
    assert client.get(f"/jobs/{backend}/applicants").status_code == 403
    assert client.get(f"/applications/{alice_app}").status_code == 403
    # Candidate cannot read the applicant list.
    client.logout()
    client.login("alice@test.local", "Password123!")
    assert client.get(f"/jobs/{backend}/applicants").status_code == 403


def test_fp_can_3_race_window_foreign_key_failure_maps_to_not_found(app, world, monkeypatch):
    """A job that vanishes between the check and the insert maps to 404, not 500.

    The test double reports the job as present for the existence check so the
    real INSERT hits the FOREIGN KEY constraint (parent row actually missing).
    """
    ids = world()
    alice = ids["users"]["alice"]

    class _PhantomResult:
        def fetchone(self):
            return object()  # non-None: the check believes the job exists

    class _PhantomJobDb:
        def __init__(self, real):
            self._real = real

        def execute(self, sql, *args, **kwargs):
            if sql.startswith("SELECT id FROM jobs"):
                return _PhantomResult()
            return self._real.execute(sql, *args, **kwargs)

    with app.app_context():
        from app.db import get_db as real_get_db

        real = real_get_db()
        monkeypatch.setattr(applications_service, "get_db", lambda: _PhantomJobDb(real))
        with pytest.raises(NotFoundError) as excinfo:
            applications_service.apply_to_job(alice, 999999)
        assert excinfo.value.status == 404
        assert excinfo.value.message == "Job not found"

        # The failed attempt leaves no partial rows behind.
        n = real.execute(
            "SELECT COUNT(*) AS n FROM applications WHERE job_id = 999999"
        ).fetchone()["n"]
        assert n == 0


def test_fp_emp_3_employer_application_detail_back_link(client, app, world):
    """The shared application page routes the employer back to the applicant list."""
    ids = world()
    alice = ids["users"]["alice"]
    backend = ids["jobs"]["backend"]
    with app.app_context():
        applications_service.apply_to_job(alice, backend)
        app_id = applications_service.list_my_applications(alice)[0]["application_id"]

    client.login("ana@test.local", "Password123!")
    page = client.get(f"/applications/{app_id}")
    assert page.status_code == 200
    assert f"href=\"/jobs/{backend}/applicants\"".encode() in page.data
    assert b'href="/applications"' not in page.data
