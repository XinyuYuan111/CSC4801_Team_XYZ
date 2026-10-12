"""System-test fixtures: a browser-faithful HTTP client (separate from ``tests/unit``).

System tests drive the app only through real HTTP semantics — status codes,
redirects, cookies, and form submissions — never through service functions.
CSRF tokens are scraped from rendered forms the way a browser would; nothing is
injected from the Flask session behind the server's back.
"""

import re

import pytest

CSRF_RE = re.compile(r'name="csrf_token"\s+value="([^"]*)"')


class Browser:
    """Cookie-preserving HTTP client on top of Flask's test client.

    CSRF tokens are scraped from rendered forms. The last scraped token is
    cached: Flask keeps one token per session, so it stays valid across pages
    (error pages carry no forms). A separate form-contract test asserts that
    every real POST form embeds the token.
    """

    def __init__(self, app):
        self.client = app.test_client()
        self.last_html = ""
        self.last_response = None
        self._csrf = None

    def get(self, url, **kwargs):
        resp = self.client.get(url, **kwargs)
        self._remember(resp)
        return resp

    def post(self, url, data=None, **kwargs):
        payload = dict(data or {})
        payload.setdefault("csrf_token", self.csrf())
        resp = self.client.post(url, data=payload, **kwargs)
        self._remember(resp)
        return resp

    def post_without_csrf(self, url, data=None, **kwargs):
        resp = self.client.post(url, data=dict(data or {}), **kwargs)
        self._remember(resp)
        return resp

    def csrf(self) -> str:
        match = CSRF_RE.search(self.last_html)
        if match:
            self._csrf = match.group(1)
        if not self._csrf:
            raise AssertionError(
                "No CSRF token seen yet — open a page with a form before posting."
            )
        return self._csrf

    def _remember(self, resp):
        self.last_response = resp
        if resp.mimetype == "text/html":
            self.last_html = resp.get_data(as_text=True)
            match = CSRF_RE.search(self.last_html)
            if match:
                self._csrf = match.group(1)

    # --- convenience flows -------------------------------------------------

    def register(self, email, password, role, display_name="", company_name=""):
        self.get("/register")
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
        self.get("/login")
        return self.post("/login", {"email": email, "password": password})

    def logout(self):
        return self.post("/logout")


@pytest.fixture()
def browser(app):
    return Browser(app)


@pytest.fixture()
def browsers(app):
    """Independent browsers (separate cookie jars) for multi-actor scenarios."""

    def _make(n=2):
        return [Browser(app) for _ in range(n)]

    return _make
