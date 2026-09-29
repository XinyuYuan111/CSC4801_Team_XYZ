"""Test fixtures: every test gets its own isolated SQLite database (FP-SEC-4)."""

import pytest

from app import create_app
from app.db import get_db, init_db
from app.services import applications as applications_service
from app.services import auth as auth_service
from app.services import jobs as jobs_service
from app.services import profiles as profiles_service
from app.services import scheduling as scheduling_service
from app.timeutils import to_iso, utc_now
from datetime import timedelta


class FormClient:
    """Test client wrapper that attaches a CSRF token to every POST (like base.html)."""

    def __init__(self, client):
        self._client = client

    def _csrf(self) -> str:
        with self._client.session_transaction() as sess:
            if "csrf_token" not in sess:
                sess["csrf_token"] = "test-csrf-token"
            return sess["csrf_token"]

    def post(self, url, data=None, **kwargs):
        payload = dict(data or {})
        payload.setdefault("csrf_token", self._csrf())
        return self._client.post(url, data=payload, **kwargs)

    def get(self, url, **kwargs):
        return self._client.get(url, **kwargs)

    def register(self, email, password, role, display_name="", company_name=""):
        return self.post(
            "/register",
            {
                "email": email,
                "password": password,
                "role": role,
                "display_name": display_name,
                "company_name": company_name,
            },
        )

    def login(self, email, password):
        return self.post("/login", {"email": email, "password": password})

    def logout(self):
        return self.post("/logout")


@pytest.fixture()
def app(tmp_path):
    """Flask app with an isolated test database file per test function."""
    database = tmp_path / "test.sqlite3"
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "unit-test-secret-key",
            "DATABASE": str(database),
        }
    )
    with app.app_context():
        init_db()
    yield app


@pytest.fixture()
def client(app):
    return FormClient(app.test_client())


@pytest.fixture()
def db(app):
    with app.app_context():
        yield get_db()


@pytest.fixture()
def world(app):
    """Standard fixture world: 2 candidates, 2 employers, 2 jobs, mixed applications.

    Skills are chosen so the FP-MATCH-1 examples show up as real rows:
    Alice (python, sql) vs Backend (python, sql) -> 100
    Bob   (python)       vs Backend (python, sql) -> 50
    Cara  (rust)         vs Backend (python, sql) -> 0   (Cara added by tests when needed)
    any                  vs Analyst ()            -> 100
    """

    def build(include_cara: bool = False):
        with app.app_context():
            ids = {"users": {}, "jobs": {}, "applications": {}, "slots": {}}
            ids["users"]["alice"] = auth_service.register_user(
                "alice@test.local", "Password123!", "Candidate", display_name="Alice Chen"
            )
            ids["users"]["bob"] = auth_service.register_user(
                "bob@test.local", "Password123!", "Candidate", display_name="Bob Patel"
            )
            if include_cara:
                ids["users"]["cara"] = auth_service.register_user(
                    "cara@test.local", "Password123!", "Candidate", display_name="Cara Diaz"
                )
            ids["users"]["ana"] = auth_service.register_user(
                "ana@test.local", "Password123!", "Employer", company_name="Acme Corp"
            )
            ids["users"]["ben"] = auth_service.register_user(
                "ben@test.local", "Password123!", "Employer", company_name="Globex Inc"
            )
            profiles_service.update_candidate_profile(
                ids["users"]["alice"], "Alice Chen", "Python, SQL"
            )
            profiles_service.update_candidate_profile(ids["users"]["bob"], "Bob Patel", "Python")
            if include_cara:
                profiles_service.update_candidate_profile(
                    ids["users"]["cara"], "Cara Diaz", "Rust"
                )
            profiles_service.update_company(
                ids["users"]["ana"], "Acme Corp", "Infrastructure tooling."
            )
            profiles_service.update_company(
                ids["users"]["ben"], "Globex Inc", "Analytics products."
            )
            ids["jobs"]["backend"] = jobs_service.create_job(
                ids["users"]["ana"], "Backend Engineer", "APIs in Python.", "Python, SQL"
            )
            ids["jobs"]["analyst"] = jobs_service.create_job(
                ids["users"]["ben"], "Data Analyst", "Product analytics.", ""
            )
        return ids

    return build


def make_future_slot_start() -> str:
    """A guaranteed-future ISO UTC start time (tomorrow at 15:00 UTC)."""
    day = (utc_now() + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    return to_iso(day)


def make_slot_end(start_iso: str) -> str:
    from app.timeutils import plus_minutes

    return plus_minutes(start_iso, 30)
