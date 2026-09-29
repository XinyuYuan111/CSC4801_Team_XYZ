"""Verification evidence for FP-DOC-3: the seed command builds the required dataset."""

from app.matching import match_score
from app.seed import DEMO_PASSWORD, seed_demo_data
from app.services import applications as applications_service
from app.services import jobs as jobs_service
from app.services import profiles as profiles_service
from app.services import scheduling as scheduling_service


def test_fp_doc_3_deterministic_seed_dataset(app):
    with app.app_context():
        ids = seed_demo_data()
        from app.db import get_db

        # Two candidates and two employers at minimum (we seed three candidates
        # so the zero-score matching example has its own row).
        roles = {row["role"] for row in get_db().execute("SELECT role FROM users")}
        assert roles == {"Candidate", "Employer"}
        counts = {
            role: get_db()
            .execute("SELECT COUNT(*) AS n FROM users WHERE role = ?", (role,))
            .fetchone()["n"]
            for role in roles
        }
        assert counts["Candidate"] >= 2
        assert counts["Employer"] >= 2

        # FP-DOC-3 "two jobs with required skills": at least two jobs carry a
        # non-empty skills list; the empty-skill job is the FP-MATCH-1 example-4
        # carrier and is additive to that minimum.
        jobs = [jobs_service.get_job(job_id) for job_id in ids["jobs"].values()]
        with_skills = [job for job in jobs if job["required_skills"]]
        without_skills = [job for job in jobs if not job["required_skills"]]
        assert len(with_skills) >= 2
        assert len(without_skills) >= 1
        backend = jobs_service.get_job(ids["jobs"]["backend"])
        frontend = jobs_service.get_job(ids["jobs"]["frontend"])
        open_job = jobs_service.get_job(ids["jobs"]["open"])
        assert backend["required_skills"] == ["python", "sql"]
        assert frontend["required_skills"] == ["javascript"]
        assert open_job["required_skills"] == []

        # The four FP-MATCH-1 examples appear as literal (C, R) pairs.
        alice = profiles_service.get_candidate_profile(ids["users"]["alice"])
        bob = profiles_service.get_candidate_profile(ids["users"]["bob"])
        cara = profiles_service.get_candidate_profile(ids["users"]["cara"])
        assert alice["skills"] == ["python", "sql"]  # example 1: C == R -> 100
        assert match_score(alice["skills"], backend["required_skills"]) == 100
        assert match_score(bob["skills"], backend["required_skills"]) == 50  # example 2
        assert match_score(cara["skills"], backend["required_skills"]) == 0  # example 3
        assert match_score(cara["skills"], open_job["required_skills"]) == 100  # example 4
        assert match_score(alice["skills"], open_job["required_skills"]) == 100

        # Applications cover all four statuses.
        statuses = {row["status"] for row in get_db().execute("SELECT status FROM applications")}
        assert statuses == {"Pending", "Interviewing", "Rejected", "Accepted"}

        # Two Interviewing candidates are eligible to race for the same slot.
        alice_apps = applications_service.list_my_applications(ids["users"]["alice"])
        bob_apps = applications_service.list_my_applications(ids["users"]["bob"])
        racing = [
            a
            for a in alice_apps + bob_apps
            if a["status"] == "Interviewing" and a["company_name"] == "Acme Corp"
        ]
        assert len(racing) == 2
        available = scheduling_service.list_available_slots(ids["users"]["ana"])
        assert len(available) >= 1

        # Demo credentials are marked local/demo and use one shared demo password.
        assert DEMO_PASSWORD == "DemoPass123!"
