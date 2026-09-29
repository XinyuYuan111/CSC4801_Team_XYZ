"""Deterministic skill-overlap matching (FP-MATCH-1).

This module is the single matching implementation used by both the candidate
and employer views. Resume text is never an input.

Normalization: trim surrounding whitespace, convert to lowercase, drop empty
values, drop duplicates. With ``C`` and ``R`` the resulting sets::

    score = 100                                      when |R| = 0
    score = floor(100 * |C intersection R| / |R|)    otherwise

The result is an integer in [0, 100].
"""

from typing import Iterable, Sequence


def normalize_skills(raw: Iterable[str]) -> list[str]:
    """Trim, lowercase, drop empties and duplicates, preserving first-seen order."""
    seen: set[str] = set()
    skills: list[str] = []
    for item in raw:
        skill = (item or "").strip().lower()
        if skill and skill not in seen:
            seen.add(skill)
            skills.append(skill)
    return skills


def parse_skills_text(text: str) -> list[str]:
    """Parse a comma/newline separated skills field into normalized skills."""
    if not text:
        return []
    parts: list[str] = []
    for line in text.replace("\n", ",").split(","):
        parts.append(line)
    return normalize_skills(parts)


def match_score(candidate_skills: Iterable[str], required_skills: Iterable[str]) -> int:
    """Return the integer skill-overlap score for one candidate and one job."""
    c = set(normalize_skills(candidate_skills))
    r = set(normalize_skills(required_skills))
    if not r:
        return 100
    return 100 * len(c & r) // len(r)


def sort_jobs_for_candidate(rows: Sequence[dict]) -> list[dict]:
    """Sort candidate-dashboard rows: score desc, title (case-insensitive) asc, job id asc."""
    return sorted(rows, key=lambda row: (-row["score"], row["title"].lower(), row["job_id"]))


def sort_applicants_for_employer(rows: Sequence[dict]) -> list[dict]:
    """Sort employer-applicant rows: score desc, display name (case-insensitive) asc, candidate id asc."""
    return sorted(
        rows,
        key=lambda row: (-row["score"], row["display_name"].lower(), row["candidate_id"]),
    )
