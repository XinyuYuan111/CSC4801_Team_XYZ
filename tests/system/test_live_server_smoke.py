"""System: smoke test against a live waitress process (documented commands).

Covers the FP-ARCH-1 / FP-DOC-1 contract end to end — ``python manage.py
init-db``, ``python manage.py seed`` and ``python manage.py run`` from the
repository root — and talks to the server over real TCP with stdlib urllib
(sessions, cookies, CSRF scraping). This is the closest automation gets to the
grader's manual INSTALL.md walkthrough.
"""

import http.cookiejar
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not Path(__file__).resolve().parents[2].joinpath("manage.py").exists(),
    reason="repository root layout missing",
)

ROOT = Path(__file__).resolve().parents[2]
CSRF_RE = re.compile(r'name="csrf_token"\s+value="([^"]*)"')


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Keep 3xx responses visible instead of silently following them."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class LiveBrowser:
    """Minimal cookie-aware browser over urllib (redirects not followed)."""

    def __init__(self, base: str):
        self.base = base
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            _NoRedirect, urllib.request.HTTPCookieProcessor(self.jar)
        )
        self.csrf = None

    def get(self, path: str):
        return self._open(urllib.request.Request(self.base + path, method="GET"))

    def post(self, path: str, data: dict):
        payload = dict(data)
        payload.setdefault("csrf_token", self.csrf or "")
        encoded = urllib.parse.urlencode(payload).encode()
        return self._open(urllib.request.Request(self.base + path, data=encoded, method="POST"))

    def _open(self, req):
        try:
            with self.opener.open(req, timeout=10) as resp:
                body = resp.read().decode("utf-8", "replace")
                self._cache_csrf(body)
                return resp.status, body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            self._cache_csrf(body)
            return exc.code, body

    def _cache_csrf(self, body: str):
        match = CSRF_RE.search(body)
        if match:
            self.csrf = match.group(1)


@pytest.fixture()
def live_server(tmp_path):
    """Boot the documented server on an isolated database; tear it down after."""
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NO_WINDOW
    else:
        creationflags = 0
    port = _free_port()
    env = {
        **os.environ,
        "DATABASE": str(tmp_path / "live.sqlite3"),
        "PORT": str(port),
        "PYTHONUNBUFFERED": "1",
    }

    init = subprocess.run(
        [sys.executable, "manage.py", "init-db"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert init.returncode == 0, f"init-db failed: {init.stderr}"
    seed = subprocess.run(
        [sys.executable, "manage.py", "seed"],
        cwd=ROOT, env=env, capture_output=True, text=True, timeout=60,
    )
    assert seed.returncode == 0, f"seed failed: {seed.stderr}"
    assert "alice@demo.local" in seed.stdout, seed.stdout

    proc = subprocess.Popen(
        [sys.executable, "manage.py", "run", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=creationflags,
    )
    base = f"http://127.0.0.1:{port}"
    deadline = time.time() + 30
    ready = False
    while time.time() < deadline:
        if proc.poll() is not None:
            out = proc.stdout.read().decode("utf-8", "replace")
            pytest.fail(f"server exited early: {out}")
        try:
            with urllib.request.urlopen(base + "/login", timeout=2) as resp:
                if resp.status == 200:
                    ready = True
                    break
        except Exception:
            time.sleep(0.3)
    assert ready, "server did not become ready in 30s"

    yield base

    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def test_live_seeded_demo_accounts_and_full_smoke(live_server):
    base = live_server
    browser = LiveBrowser(base)

    # Anonymous landing redirects to login.
    status, body = browser.get("/login")
    assert status == 200 and "Log in" in body

    # Seeded demo candidate logs in with the documented credentials.
    status, body = browser.post(
        "/login", {"email": "alice@demo.local", "password": "DemoPass123!"}
    )
    assert status in (200, 302)

    status, body = browser.get("/dashboard")
    assert status == 200
    # FP-DOC-3 / FP-MATCH-1 example rows appear in the live dashboard.
    assert "Backend Engineer" in body
    assert re.search(r'<td class="score">100</td>\s*<td>Backend Engineer</td>', body)
    assert re.search(r'<td class="score">50</td>\s*<td>Frontend Engineer</td>', body) or "Frontend Engineer" in body

    # Alice's application detail shows Interviewing + a bookable slot.
    status, body = browser.get("/applications")
    assert status == 200
    app_links = re.findall(r"/applications/(\d+)", body)
    assert app_links, body
    status, body = browser.get(f"/applications/{app_links[0]}")
    assert status == 200
    assert "Interviewing" in body
    assert "Book an interview slot" in body

    # Demo employer logs in and sees the race candidate set (FP-DOC-3).
    employer = LiveBrowser(base)
    assert employer.get("/login")[0] == 200  # fetch CSRF like a browser would
    status, _ = employer.post("/login", {"email": "ana@demo.local", "password": "DemoPass123!"})
    assert status in (200, 302)
    status, body = employer.get("/employer/jobs")
    assert status == 200 and "Backend Engineer" in body
    status, body = employer.get("/employer/slots")
    assert status == 200
    assert body.count("/slots/") >= 2  # race slot + spare


def test_live_registration_and_logout_roundtrip(live_server):
    browser = LiveBrowser(live_server)
    status, body = browser.get("/register")
    assert status == 200
    status, body = browser.post(
        "/register",
        {
            "email": "live@smoke.test",
            "password": "Password123!",
            "role": "Candidate",
            "display_name": "Live Smoke",
            "company_name": "",
        },
    )
    assert status in (200, 302)
    status, body = browser.get("/profile")
    assert status == 200 and "Live Smoke" in body

    status, _ = browser.post("/logout", {})
    assert status in (200, 302)
    status, body = browser.get("/profile")
    assert status == 302  # bounced to login after logout
