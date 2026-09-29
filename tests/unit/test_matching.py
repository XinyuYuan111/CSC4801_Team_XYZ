"""Unit tests for FP-MATCH-1: skill-overlap score, normalization, and tie-breaking."""

from app.matching import (
    match_score,
    normalize_skills,
    parse_skills_text,
    sort_applicants_for_employer,
    sort_jobs_for_candidate,
)


def test_fp_match_1_examples_normalization_and_floor():
    # The four required examples from FP-MATCH-1.
    assert match_score(["Python", "SQL"], ["Python", "SQL"]) == 100
    assert match_score(["Python"], ["Python", "SQL"]) == 50
    assert match_score(["Rust"], ["Python", "SQL"]) == 0
    assert match_score([], []) == 100
    assert match_score(["Anything", "Goes"], []) == 100

    # Normalization: trim, lowercase, drop empties, drop duplicates.
    assert match_score(["  Python  ", "python", "SQL", ""], ["PYTHON", "sql"]) == 100
    assert normalize_skills(["  Python ", "python", "", "  ", "SQL"]) == ["python", "sql"]
    assert parse_skills_text(" Python, SQL ,, python \n Rust ") == ["python", "sql", "rust"]

    # Integer floor, not rounding: 2 of 3 = floor(200/3) = 66 (never 67).
    assert match_score(["a", "b"], ["a", "b", "c"]) == 66
    assert match_score(["a"], ["a", "b", "c"]) == 33
    assert match_score(["a", "b", "c", "d"], ["a", "b", "c"]) == 100

    # Result is always an integer in [0, 100].
    for candidate, required in ((["x"], ["y"]), (["a"], ["a"]), (["q"], ["a", "b"])):
        score = match_score(candidate, required)
        assert isinstance(score, int)
        assert 0 <= score <= 100


def test_fp_match_1_both_tie_breakers():
    # Candidate dashboard: score desc, then case-insensitive title, then stable job id.
    rows = [
        {"job_id": 3, "title": "beta", "score": 50},
        {"job_id": 1, "title": "Alpha", "score": 50},
        {"job_id": 2, "title": "alpha", "score": 50},  # same title lowercased as job 1: id breaks the tie
        {"job_id": 5, "title": "Zeta", "score": 100},
        {"job_id": 4, "title": "Gamma", "score": 0},
    ]
    ordered = sort_jobs_for_candidate(rows)
    assert [row["job_id"] for row in ordered] == [5, 1, 2, 3, 4]

    # "Apple" vs "apple pie" ordering is case-insensitive on the title.
    rows = [
        {"job_id": 2, "title": "apple pie", "score": 10},
        {"job_id": 1, "title": "Apple", "score": 10},
    ]
    ordered = sort_jobs_for_candidate(rows)
    assert [row["job_id"] for row in ordered] == [1, 2]

    # Employer applicants: score desc, then case-insensitive display name, then stable candidate id.
    rows = [
        {"candidate_id": 9, "display_name": "dana", "score": 80},
        {"candidate_id": 2, "display_name": "Bob", "score": 80},
        {"candidate_id": 1, "display_name": "bob", "score": 80},  # same name lowercased: id breaks the tie
        {"candidate_id": 7, "display_name": "Zed", "score": 100},
    ]
    ordered = sort_applicants_for_employer(rows)
    assert [row["candidate_id"] for row in ordered] == [7, 1, 2, 9]
