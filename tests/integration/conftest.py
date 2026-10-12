"""Integration-test fixtures (separate from the spec-required ``tests/unit`` suite).

Integration tests exercise several application layers together — routes,
services, and the real SQLite schema — rather than one unit in isolation.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest


@pytest.fixture()
def run_in_context(app):
    """Run a callable inside its own app context (its own SQLite connection)."""

    def _run(fn):
        with app.app_context():
            return fn()

    return _run


def race(app, *fns, start_timeout: float = 15.0):
    """Run ``fns`` concurrently in separate app contexts (separate connections).

    Returns one result per callable: either its return value, or the exception
    it raised. A barrier releases all threads at once so the calls genuinely
    overlap instead of being serialized by scheduling luck.
    """
    barrier = threading.Barrier(len(fns))
    results: list = [None] * len(fns)

    def worker(index, fn):
        with app.app_context():
            barrier.wait(timeout=start_timeout)
            try:
                results[index] = fn()
            except Exception as exc:  # noqa: BLE001 - surfaced to assertions
                results[index] = exc

    with ThreadPoolExecutor(max_workers=len(fns)) as pool:
        futures = [pool.submit(worker, i, fn) for i, fn in enumerate(fns)]
        for future in futures:
            future.result(timeout=start_timeout)
    return results


@pytest.fixture()
def race_calls(app):
    return lambda *fns: race(app, *fns)
