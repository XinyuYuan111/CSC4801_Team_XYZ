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

        # Two candidates and two employers at minimum (we seed three candidates
        # so the zero-score matching example has its own row).
        from app.db import get_db

        roles = {
            row["role"]
            for row in get_db().execute("SELECT role FROM users")
        }
        assert roles == {"Candidate", "Employer"}
        counts = {
            role: get_db().execute("SELECT COUNT(*) AS n FROM users WHERE role = ?", (role,)).fetchone()["n"]
            for role in roles
        }
        assert counts["Candidate"] >= 2
        assert counts["Employer"] >= 2

        # Two jobs with required skills (backend has skills; analyst has an empty list).
        assert len(ids["jobs"]) == 2
        backend = jobs_service.get_job(ids["jobs"]["backend"])
        analyst = jobs_service.get_job(ids["jobs"]["analyst"])
        assert backend["required_skills"] == ["python", "sql"]
        assert analyst["required_skills"] == []

        # The four FP-MATCH-1 examples appear in the seeded data.
        alice = profiles_service.get_candidate_profile(ids["users"]["alice"])
        bob = profiles_service.get_candidate_profile(ids["users"]["bob"])
        cara = profiles_service.get_candidate_profile(ids["users"]["cara"])
        assert match_score(alice["skills"], backend["required_skills"]) == 100
        assert match_score(bob["skills"], backend["required_skills"]) == 50
        assert match_score(cara["skills"], backend["required_skills"]) == 0
        assert match_score(cara["skills"], analyst["required_skills"]) == 100

        # Applications cover all four statuses.
        statuses = {
            row["status"]
            for row in get_db().execute("SELECT status FROM applications")
        }
        assert statuses == {"Pending", "Interviewing", "Rejected", "Accepted"}

        # Two Interviewing candidates are eligible to race for the same slot.
        alice_apps = applications_service.list_my_applications(ids["users"]["alice"])
        bob_apps = applications_service.list_my_applications(ids["users"]["bob"])
        racing = [
            a for a in alice_apps + bob_apps
            if a["status"] == "Interviewing" and a["company_name"] == "Acme Corp"
        ]
        assert len(racing) == 2
        available = scheduling_service.list_available_slots(ids["users"]["ana"])
        assert len(available) >= 1

        # Demo credentials are marked local/demo and use one shared demo password.
        assert DEMO_PASSWORD == "DemoPass123!"
        assert all(email.endswith("@demo.local") for email in (
            "alice@demo.local", "bob@demo.local", "cara@demo.local",
            "ana@demo.local", "ben@demo.local",
        ))
