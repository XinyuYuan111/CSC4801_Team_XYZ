"""Deterministic demo data (FP-DOC-3).

``python manage.py seed`` resets the database and inserts the fixed dataset
below. Slot start times are computed relative to the seed run so they are
always in the future; everything else is constant.

Demo credentials (local/demo only, never real accounts):

- alice@demo.local  / DemoPass123!  Candidate "Alice Chen"  — Python, SQL
- bob@demo.local    / DemoPass123!  Candidate "Bob Patel"   — Python
- cara@demo.local   / DemoPass123!  Candidate "Cara Diaz"   — Rust
- ana@demo.local    / DemoPass123!  Employer  "Acme Corp"
- ben@demo.local    / DemoPass123!  Employer  "Globex Inc"

Jobs (FP-DOC-3: two jobs with required skills + one empty-skill job that is the
carrier for FP-MATCH-1 example 4):

- job "Backend Engineer"  @ Acme Corp  (skills: python, sql)
- job "Frontend Engineer" @ Globex Inc (skills: javascript)
- job "Open Application"  @ Globex Inc (skills: empty list)

The four FP-MATCH-1 examples appear literally as:

| Candidate | Job              | Skills C    | Skills R    | Score |
|-----------|------------------|-------------|-------------|-------|
| Alice     | Backend Engineer | python, sql | python, sql | 100   |
| Bob       | Backend Engineer | python      | python, sql | 50    |
| Cara      | Backend Engineer | rust        | python, sql | 0     |
| any       | Open Application | any         | (empty)     | 100   |

Applications cover all four statuses, and Alice and Bob are both
``Interviewing`` on Backend Engineer and can race for the same available slot.
"""

from datetime import timedelta

from app.db import reset_db
from app.services import applications as applications_service
from app.services import auth as auth_service
from app.services import jobs as jobs_service
from app.services import profiles as profiles_service
from app.services import scheduling as scheduling_service
from app.timeutils import to_iso, utc_now

DEMO_PASSWORD = "DemoPass123!"


def seed_demo_data() -> dict:
    """Reset and seed the local database. Returns ids of the created rows."""
    reset_db()

    ids: dict = {"users": {}, "jobs": {}, "applications": {}, "slots": {}}

    ids["users"]["alice"] = auth_service.register_user(
        "alice@demo.local", DEMO_PASSWORD, "Candidate", display_name="Alice Chen"
    )
    ids["users"]["bob"] = auth_service.register_user(
        "bob@demo.local", DEMO_PASSWORD, "Candidate", display_name="Bob Patel"
    )
    ids["users"]["cara"] = auth_service.register_user(
        "cara@demo.local", DEMO_PASSWORD, "Candidate", display_name="Cara Diaz"
    )
    ids["users"]["ana"] = auth_service.register_user(
        "ana@demo.local", DEMO_PASSWORD, "Employer", company_name="Acme Corp"
    )
    ids["users"]["ben"] = auth_service.register_user(
        "ben@demo.local", DEMO_PASSWORD, "Employer", company_name="Globex Inc"
    )

    # Alice's skills are exactly "Python, SQL" so FP-MATCH-1 example 1 appears
    # as the literal (C={python,sql}, R={python,sql}) pair in the seed data.
    profiles_service.update_candidate_profile(ids["users"]["alice"], "Alice Chen", "Python, SQL")
    profiles_service.replace_resume(
        ids["users"]["alice"],
        ids["users"]["alice"],
        "Alice Chen\nBackend developer with Python and SQL experience.\n"
        "<i>Formatted HTML in resumes is escaped when rendered.</i>",
    )
    profiles_service.update_candidate_profile(ids["users"]["bob"], "Bob Patel", "Python")
    profiles_service.replace_resume(
        ids["users"]["bob"], ids["users"]["bob"], "Bob Patel\nPython developer, one year of experience."
    )
    profiles_service.update_candidate_profile(ids["users"]["cara"], "Cara Diaz", "Rust")
    profiles_service.replace_resume(
        ids["users"]["cara"], ids["users"]["cara"], "Cara Diaz\nSystems programmer focused on Rust."
    )

    profiles_service.update_company(
        ids["users"]["ana"], "Acme Corp", "Infrastructure tooling for modern teams."
    )
    profiles_service.update_company(
        ids["users"]["ben"], "Globex Inc", "Analytics products for global markets."
    )

    ids["jobs"]["backend"] = jobs_service.create_job(
        ids["users"]["ana"], "Backend Engineer",
        "Design and build APIs in Python. SQL data modeling required.",
        "Python, SQL",
    )
    ids["jobs"]["frontend"] = jobs_service.create_job(
        ids["users"]["ben"], "Frontend Engineer",
        "Build accessible web interfaces with JavaScript.",
        "JavaScript",
    )
    ids["jobs"]["open"] = jobs_service.create_job(
        ids["users"]["ben"], "Open Application",
        "General application with no specific skill requirements.",
        "",
    )

    ids["applications"]["alice_backend"] = applications_service.apply_to_job(
        ids["users"]["alice"], ids["jobs"]["backend"]
    )
    ids["applications"]["bob_backend"] = applications_service.apply_to_job(
        ids["users"]["bob"], ids["jobs"]["backend"]
    )
    ids["applications"]["cara_backend"] = applications_service.apply_to_job(
        ids["users"]["cara"], ids["jobs"]["backend"]
    )
    ids["applications"]["alice_frontend"] = applications_service.apply_to_job(
        ids["users"]["alice"], ids["jobs"]["frontend"]
    )
    ids["applications"]["bob_open"] = applications_service.apply_to_job(
        ids["users"]["bob"], ids["jobs"]["open"]
    )

    # All four statuses. Alice and Bob stay Interviewing on the backend job so
    # they can race for the same available slot (FP-DOC-3, FP-SCHED-3).
    applications_service.set_status(ids["users"]["ana"], ids["applications"]["alice_backend"], "Interviewing")
    applications_service.set_status(ids["users"]["ana"], ids["applications"]["bob_backend"], "Interviewing")
    applications_service.set_status(ids["users"]["ana"], ids["applications"]["cara_backend"], "Rejected")
    applications_service.set_status(ids["users"]["ben"], ids["applications"]["alice_frontend"], "Pending")
    applications_service.set_status(ids["users"]["ben"], ids["applications"]["bob_open"], "Accepted")

    # Future slots relative to seed time (UTC). The first two belong to Acme's
    # backend job: one shared race slot plus a spare. Globex gets one slot.
    base = utc_now() + timedelta(days=1)
    base = base.replace(minute=0, second=0, microsecond=0)
    start1 = to_iso(base.replace(hour=15))
    start2 = to_iso(base.replace(hour=16))
    start3 = to_iso(base.replace(hour=17))
    ids["slots"]["race"] = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], start1, to_iso(base.replace(hour=15, minute=30))
    )
    ids["slots"]["spare"] = scheduling_service.create_slot(
        ids["users"]["ana"], ids["jobs"]["backend"], start2, to_iso(base.replace(hour=16, minute=30))
    )
    ids["slots"]["globex"] = scheduling_service.create_slot(
        ids["users"]["ben"], ids["jobs"]["frontend"], start3, to_iso(base.replace(hour=17, minute=30))
    )

    return ids
