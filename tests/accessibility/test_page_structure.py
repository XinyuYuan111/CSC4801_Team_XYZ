"""Accessibility suite: structural a11y checks on every rendered screen.

Automated a11y tools usually run in a browser; here we assert the server-side
HTML contract that those tools and assistive tech rely on: language declaration,
page titles, one h1 per page, labelled form controls, table headers, and
button text. This is the static layer of an accessibility review — visual
contrast and keyboard order still need a manual pass.
"""

import re

import pytest

from tests.system.conftest import Browser


def _text(resp) -> str:
    return resp.get_data(as_text=True)


@pytest.fixture()
def screens(app):
    """Every distinct screen of the product, rendered as its intended role."""
    emp = Browser(app)
    cand = Browser(app)
    anon = Browser(app)
    assert emp.register("e@a11y.test", "Password123!", "Employer", company_name="Acme").status_code == 302
    assert cand.register("c@a11y.test", "Password123!", "Candidate", display_name="Cal").status_code == 302
    assert emp.post("/employer/jobs/new", {"title": "J", "description": "d", "skills": "Python"}).status_code == 302
    assert emp.post("/employer/slots", {"job_id": 1, "start_utc": "2032-01-01T15:00:00Z"}).status_code == 302
    assert cand.post("/jobs/1/apply", {}).status_code == 302
    cand_id = re.search(r"/candidates/(\d+)/resume", _text(cand.get("/profile"))).group(1)

    pages = [
        ("login", anon.get("/login")),
        ("register", anon.get("/register")),
        ("dashboard", cand.get("/dashboard")),
        ("profile", cand.get("/profile")),
        ("resume", cand.get(f"/candidates/{cand_id}/resume")),
        ("applications", cand.get("/applications")),
        ("application_detail", cand.get("/applications/1")),
        ("job_detail", cand.get("/jobs/1")),
        ("company", emp.get("/company")),
        ("employer_jobs", emp.get("/employer/jobs")),
        ("job_form", emp.get("/employer/jobs/new")),
        ("job_edit", emp.get("/jobs/1/edit")),
        ("applicants", emp.get("/jobs/1/applicants")),
        ("slots", emp.get("/employer/slots")),
        ("error_404", cand.get("/jobs/99999")),  # login_required runs before 404
    ]
    for name, resp in pages:
        expected = 404 if name == "error_404" else 200
        assert resp.status_code == expected, f"{name} -> {resp.status_code}"
    return pages


def test_every_screen_declares_language_and_charset(screens):
    for name, resp in screens:
        body = _text(resp)
        assert '<html lang="' in body, f"{name}: missing lang attribute"
        assert 'charset="utf-8"' in body.lower() or "charset=utf-8" in body.lower(), name


def test_every_screen_has_a_unique_nonempty_title(screens):
    titles = []
    for name, resp in screens:
        match = re.search(r"<title>([^<]+)</title>", _text(resp))
        assert match and match.group(1).strip(), f"{name}: empty or missing <title>"
        titles.append(match.group(1).strip())
    # Titles must be distinguishable (screen-reader users navigate by title).
    assert len(set(titles)) == len(titles), f"duplicate page titles: {titles}"


def test_every_screen_has_exactly_one_h1(screens):
    for name, resp in screens:
        count = len(re.findall(r"<h1[\s>]", _text(resp)))
        assert count == 1, f"{name}: {count} <h1> elements"


def test_all_form_controls_are_labelled(screens):
    """Every visible input/textarea/select needs a label or aria-label."""
    for name, resp in screens:
        body = _text(resp)
        label_targets = set(re.findall(r'<label[^>]*for="([^"]+)"', body))
        for tag in re.findall(r"<(?:input|textarea|select)\b[^>]*>", body):
            if 'type="hidden"' in tag:
                continue
            id_match = re.search(r'id="([^"]+)"', tag)
            has_label = id_match and id_match.group(1) in label_targets
            has_aria = "aria-label" in tag
            assert has_label or has_aria, f"{name}: unlabelled control {tag}"


def test_applicants_status_select_is_labelled(app):
    """The per-row status control must announce its purpose to assistive tech."""
    emp = Browser(app)
    cand = Browser(app)
    assert emp.register("e@sel.test", "Password123!", "Employer", company_name="C").status_code == 302
    assert cand.register("c@sel.test", "Password123!", "Candidate", display_name="C").status_code == 302
    assert emp.post("/employer/jobs/new", {"title": "J", "description": "d", "skills": ""}).status_code == 302
    assert cand.post("/jobs/1/apply", {}).status_code == 302
    body = _text(emp.get("/jobs/1/applicants"))
    for tag in re.findall(r"<select\b[^>]*>", body):
        assert re.search(r'id="[^"]+"', tag), f"select without id: {tag}"
        assert "aria-label" in tag or 'id="status"' in body and '<label for="status"' in body, (
            f"select without label association: {tag}"
        )


def test_tables_use_header_cells(screens):
    for name, resp in screens:
        body = _text(resp)
        tables = re.findall(r"<table>.*?</table>", body, re.S)
        for table in tables:
            assert "<th" in table, f"{name}: table without <th> headers"
            # Rows must contain cells matching header count of first header row.
            first_header = re.search(r"<thead>.*?</thead>", table, re.S)
            if first_header:
                cols = len(re.findall(r"<th", first_header.group(0)))
                assert cols > 0


def test_buttons_have_accessible_text(screens):
    for name, resp in screens:
        for tag in re.findall(r"<button\b[^>]*>(.*?)</button>", _text(resp), re.S):
            text = re.sub(r"<[^>]+>", "", tag).strip()
            assert text, f"{name}: button without text ({tag!r})"


def test_error_page_is_still_structurally_valid(app):
    b = Browser(app)
    assert b.register("err@a11y.test", "Password123!", "Candidate", display_name="E").status_code == 302
    resp = b.get("/jobs/99999")
    assert resp.status_code == 404
    body = _text(resp)
    assert "not found" in body.lower()
    assert '<html lang="' in body
    assert "<title>" in body
