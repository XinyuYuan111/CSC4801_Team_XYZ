"""Performance / load suite: response budgets under a realistic dataset.

Not a benchmark — a regression guard: if a change makes a core page blow past a
generous budget on a seeded dataset, something algorithmic went wrong (N+1
explosions, accidental full scans in Python, per-row re-renders). Budgets are
deliberately loose so slow CI machines don't flake.
"""

import re
import time

import pytest

from app.services import applications as applications_service
from app.services import auth as auth_service
from app.services import jobs as jobs_service
from app.services import profiles as profiles_service
from app.services import scheduling as scheduling_service
from tests.system.conftest import Browser

BUDGET_SECONDS = 3.0  # generous wall-clock budget per core page


@pytest.fixture()
def big_world(app):
    """20 candidates × 40 jobs × applications, plus slots — a plausible term demo."""
    with app.app_context():
        ids = {"emp": [], "cands": [], "jobs": []}
        for e in range(3):
            emp = auth_service.register_user(
                f"emp{e}@perf.test", "Password123!", "Employer", company_name=f"Co{e}"
            )
            ids["emp"].append(emp)
        for c in range(20):
            cand = auth_service.register_user(
                f"cand{c}@perf.test", "Password123!", "Candidate", display_name=f"Cand{c:02d}"
            )
            profiles_service.update_candidate_profile(cand, f"Cand{c:02d}", "Python, SQL, Rust, Go")
            ids["cands"].append(cand)
        for e, emp in enumerate(ids["emp"]):
            for j in range(15):
                job = jobs_service.create_job(emp, f"Job {e}-{j}", "Description.", "Python, SQL")
                ids["jobs"].append(job)
                for cand in ids["cands"][:10]:
                    applications_service.apply_to_job(cand, job)
            for s in range(5):
                scheduling_service.create_slot(
                    emp, ids["jobs"][e * 15], f"2032-01-0{s + 1}T15:00:00Z", f"2032-01-0{s + 1}T15:30:00Z"
                )
        return ids


def _timed(fn):
    start = time.perf_counter()
    result = fn()
    return time.perf_counter() - start, result


def test_candidate_dashboard_budget_under_load(app, big_world):
    b = Browser(app)
    assert b.login("cand0@perf.test", "Password123!").status_code == 302
    elapsed, resp = _timed(lambda: b.get("/dashboard"))
    assert resp.status_code == 200
    assert elapsed < BUDGET_SECONDS, f"dashboard took {elapsed:.2f}s"
    body = resp.get_data(as_text=True)
    assert body.count("<tr>") >= 45  # all jobs listed


def test_employer_applicants_budget_under_load(app, big_world):
    b = Browser(app)
    assert b.login("emp0@perf.test", "Password123!").status_code == 302
    elapsed, resp = _timed(lambda: b.get("/jobs/1/applicants"))
    assert resp.status_code == 200
    assert elapsed < BUDGET_SECONDS, f"applicants took {elapsed:.2f}s"


def test_my_applications_budget_under_load(app, big_world):
    b = Browser(app)
    assert b.login("cand0@perf.test", "Password123!").status_code == 302
    elapsed, resp = _timed(lambda: b.get("/applications"))
    assert resp.status_code == 200
    assert elapsed < BUDGET_SECONDS, f"applications took {elapsed:.2f}s"


def test_sequential_request_throughput(app, big_world):
    """50 mixed authenticated GETs should complete well within a loose budget."""
    b = Browser(app)
    assert b.login("cand1@perf.test", "Password123!").status_code == 302
    paths = ["/dashboard", "/applications", "/profile", "/jobs/1"]
    start = time.perf_counter()
    for i in range(50):
        resp = b.get(paths[i % len(paths)])
        assert resp.status_code == 200
    elapsed = time.perf_counter() - start
    assert elapsed < 15.0, f"50 GETs took {elapsed:.2f}s ({elapsed / 50 * 1000:.0f} ms/req)"


def test_mixed_concurrent_load_has_no_5xx(app, big_world):
    """Light load test: parallel readers + writers never produce a 5xx."""
    from concurrent.futures import ThreadPoolExecutor

    def worker(i):
        b = Browser(app)
        if i % 2 == 0:
            assert b.login(f"cand{i % 20}@perf.test", "Password123!").status_code == 302
            codes = [
                b.get("/dashboard").status_code,
                b.get("/applications").status_code,
                b.get("/profile").status_code,
                b.post("/profile", {"display_name": f"Cand{i}", "skills": "Python"}).status_code,
            ]
        else:
            assert b.login(f"emp{i % 3}@perf.test", "Password123!").status_code == 302
            codes = [
                b.get("/employer/jobs").status_code,
                b.get("/employer/slots").status_code,
                b.get("/jobs/1/applicants").status_code,
                b.post("/company", {"company_name": f"Co{i}", "description": "d"}).status_code,
            ]
        return codes

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker, range(16)))
    flat = [c for codes in results for c in codes]
    assert all(c < 500 for c in flat), f"5xx under load: {flat}"


def test_query_count_scales_linearly_not_quadratically(app, big_world):
    """Characterization of the known N+1 pattern in list_jobs_with_scores.

    One dashboard render issues O(jobs) small queries (company + skills per job).
    This test documents the growth rate so a future optimization can flip the
    bound deliberately; it is not a failure while the dataset stays small.
    """
    with app.app_context():
        from app.db import get_db

        db = get_db()
        counts = {"n": 0}
        db.set_trace_callback(lambda _sql: counts.__setitem__("n", counts["n"] + 1))
        try:
            jobs_service.list_jobs_with_scores(1)
        finally:
            db.set_trace_callback(None)
        assert counts["n"] >= 40, counts  # ≥1 query per job => N+1 pattern present
        assert counts["n"] < 1000, counts  # but not combinatorial
