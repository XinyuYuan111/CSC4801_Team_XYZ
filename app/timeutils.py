"""UTC time helpers.

The system stores and displays every timestamp as UTC (documented in SPEC.md
and INSTALL.md). Slot times are ISO-8601 strings like ``2026-05-01T15:00:00Z``.
"""

from datetime import datetime, timedelta, timezone

UTC = timezone.utc
ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"
SLOT_MINUTES = 30


def utc_now() -> datetime:
    return datetime.now(tz=UTC)


def utc_now_iso() -> str:
    return to_iso(utc_now())


def to_iso(dt: datetime) -> str:
    return dt.astimezone(UTC).strftime(ISO_FMT)


def parse_iso(value: str) -> datetime:
    """Parse ``YYYY-MM-DDTHH:MM:SSZ`` (or ``+00:00``) into aware UTC datetime."""
    text = (value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_future(value: str, now: datetime | None = None) -> bool:
    return parse_iso(value) > (now or utc_now())


def plus_minutes(value: str, minutes: int) -> str:
    return to_iso(parse_iso(value) + timedelta(minutes=minutes))


def format_display(value: str) -> str:
    """Human-readable UTC rendering for templates: ``2026-05-01 15:00 UTC``."""
    return parse_iso(value).strftime("%Y-%m-%d %H:%M UTC")
