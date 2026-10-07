# TalentMatch — Recruiting and Candidate Matching

## Project Overview

TalentMatch is a two-sided recruiting platform for CSC4801. Candidates maintain a
profile, technical skills, and a private raw-text resume; browse every open job
with a deterministic skill-match score; apply once per job; and book 30-minute
interview slots once an employer moves their application to `Interviewing`.
Employers maintain a company profile, post jobs with required skills, review
applicants sorted by match score, drive applications through
`Pending / Interviewing / Rejected / Accepted`, and publish bookable interview
slots. Booking is atomic: when two candidates race for the same slot, exactly
one wins and the other receives `409 Conflict — Slot already booked`.

## Team Members

- Team XYZ (CSC4801)

## Architecture Summary

- **UI:** server-rendered Jinja2 templates served by Flask 3 (browser-based UI).
- **Backend:** Flask 3.1 application with request/route authentication and role
  checks plus a service layer (`app/services/`) for business rules and object
  ownership. Routes in `app/routes/` parse input, call services,
  render outcomes with the FP-AUTH-3 status contract (401 redirect/401, 403, 404,
  plus 409 for conflicts).
- **Database:** SQLite (persistent relational database) via the Python standard
  library `sqlite3` with **parameterized queries only**. Schema in `app/db.py`.
  Booking atomicity uses `BEGIN IMMEDIATE` transactions plus `UNIQUE` constraints
  on `bookings.slot_id` and `bookings.application_id`. Dependent foreign keys
  are `ON DELETE RESTRICT`, so job/slot deletion races can never cascade-delete
  applications or bookings.
- **Matching:** `app/matching.py` — one deterministic skill-overlap
  implementation shared by candidate and employer views (resume text is never an
  input).
- **Serving:** waitress (WSGI) in Docker and local runs.
- **Tests:** pytest unit tests in `tests/unit/` against an isolated SQLite
  database per test.

See [`SPEC.md`](SPEC.md) for the full data model, route list, matching contract,
booking transaction, and security controls.

## Quick Start

See [`INSTALL.md`](INSTALL.md) for prerequisites, install commands, migrations,
seed, run, test, and Docker build/start commands. Short version (local):

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows (bash: source .venv/bin/activate)
python -m pip install -r requirements.txt
python manage.py seed           # reset + deterministic demo data
python manage.py run            # http://127.0.0.1:8080
```

Docker:

```bash
docker build -t team-xyz .
docker run -d --name team-xyz -p 127.0.0.1:8080:8080 team-xyz
docker exec team-xyz python manage.py seed
docker exec team-xyz python -m pytest tests/unit -q
```

## Demo Accounts

Seeded **local/demo credentials only** — never use these outside a local demo
(all mailboxes use the reserved `demo.local` domain):

| Email | Password | Role | Notes |
|---|---|---|---|
| `alice@demo.local` | `DemoPass123!` | Candidate | Skills: Python, SQL — score 100 on Backend Engineer (FP-MATCH-1 example 1) |
| `bob@demo.local` | `DemoPass123!` | Candidate | Skills: Python — score 50 on Backend Engineer (example 2) |
| `cara@demo.local` | `DemoPass123!` | Candidate | Skills: Rust — score 0 on Backend Engineer (example 3) |
| `ana@demo.local` | `DemoPass123!` | Employer | Acme Corp — owns Backend Engineer + interview slots |
| `ben@demo.local` | `DemoPass123!` | Employer | Globex Inc — owns Frontend Engineer (JavaScript) and Open Application (empty required skills → 100 for everyone, example 4) |

After `python manage.py seed` the database holds two jobs **with** required
skills (Backend Engineer, Frontend Engineer) plus the empty-skill Open
Application job that carries FP-MATCH-1 example 4. Alice and Bob both have
`Interviewing` applications on Backend Engineer and can race for the same
available slot (created for tomorrow at 15:00 UTC at seed time).

## Running Unit Tests

One command, non-interactively, from the repository root (exits nonzero on
failure):

```bash
python -m pytest tests/unit -q
```

## Requirement–Test Mapping

Every requirement ID from `CSC4801_final_project/REQUIREMENTS.md` is listed.
Functional requirements map to named student-written unit tests in
`tests/unit/`; non-functional/process requirements cite verification evidence.
`FP-MATCH-2` is an unimplemented optional enhancement (`N/A`).

| Requirement ID | Behavior to verify | Implementation file(s) | Unit test(s) / verification evidence |
|---|---|---|---|
| FP-ARCH-1 | Browser UI + API/server + persistent relational DB; runs from clean checkout | `app/` (Flask+Jinja UI, service layer), `app/db.py` (SQLite), `Dockerfile`, `run.py` | Evidence: `python -m pytest tests/unit -q` green from clean checkout; `INSTALL.md` Docker build/start; no paid credentials required (no LLM in core path) |
| FP-AUTH-1 | Register / login / logout; unique email identifiers | `app/services/auth.py`, `app/routes/auth.py` | `tests/unit/test_auth.py::test_fp_auth_1_registration_and_session_lifecycle`; `tests/unit/test_auth.py::test_fp_auth_1_invalid_registration` |
| FP-AUTH-2 | Salted established password hash; no secrets in API/UI; `authenticate()` returns only non-secret columns | `app/security.py`, `app/services/auth.py` | `tests/unit/test_auth.py::test_fp_auth_2_salted_hash_and_password_verification` |
| FP-AUTH-3 | Server-side 401 (or login redirect) / 403 / 404 outcomes; authentication precedes CSRF on protected POSTs | `app/__init__.py`, `app/routes/helpers.py`, `app/services/*`, `app/errors.py`, `app/security.py` | `tests/unit/test_auth.py::test_fp_auth_3_authorization_and_missing_object`; `tests/unit/test_auth.py::test_fp_auth_3_anonymous_posts_before_csrf`; `tests/unit/test_auth.py::test_csrf_invalid_tokens_rejected_without_mutation` |
| FP-CAN-1 | Own profile + skills; private raw-text resume (403 for others) | `app/services/profiles.py`, `app/routes/candidate.py` | `tests/unit/test_workflows.py::test_fp_can_1_profile_and_private_resume_rules` |
| FP-CAN-2 | Dashboard lists all jobs with score, title, company, skills, description link; sorted by score | `app/services/jobs.py`, `app/matching.py`, `app/templates/candidate/dashboard.html` | `tests/unit/test_workflows.py::test_fp_can_2_recommendations_preserve_fields_and_rank_all_jobs` |
| FP-CAN-3 | Apply once → `Pending`; duplicate → 409 without a second row (constraint-backed); own applications show job/employer/status/booking; no cross-candidate access or status changes | `app/services/applications.py`, `app/routes/jobs.py` | `tests/unit/test_workflows.py::test_fp_can_3_pending_duplicate_and_application_owner` |
| FP-EMP-1 | Company profile view/edit (name + description) | `app/services/profiles.py`, `app/routes/employer.py` | `tests/unit/test_workflows.py::test_fp_emp_1_company_profile` |
| FP-EMP-2 | Job CRUD with title/description/skills; 403 foreign postings on **GET and POST of edit**; delete blocked by applications/slots with 409; RESTRICT FK backstop | `app/services/jobs.py`, `app/routes/employer.py` | `tests/unit/test_workflows.py::test_fp_emp_2_job_validation_and_deletion` |
| FP-EMP-3 | Applicants sorted by score with identity/skills/score/status/booking; owner sets the four statuses only; owning employer can open application detail | `app/services/applications.py`, `app/matching.py` | `tests/unit/test_workflows.py::test_fp_emp_3_applicant_fields_order_status_and_role` |
| FP-MATCH-1 | Deterministic skill-overlap score, normalization, four examples, both tie-breakers | `app/matching.py` | `tests/unit/test_matching.py::test_fp_match_1_examples_normalization_and_floor`; `tests/unit/test_matching.py::test_fp_match_1_both_tie_breakers` |
| FP-MATCH-2 | Optional AI enhancement | N/A | N/A — not implemented (see Known Limitations) |
| FP-SCHED-1 | Future 30-minute UTC slots; create/delete; reject invalid durations and past slots; booked slots undeletable and never available; expired slots labeled correctly | `app/services/scheduling.py`, `app/timeutils.py`, `app/templates/employer/slots.html` | `tests/unit/test_scheduling.py::test_fp_sched_1_slot_creation_timezones_and_deletion`; `tests/unit/test_scheduling.py::test_fp_sched_1_invalid_slots`; `tests/unit/test_scheduling.py::test_fp_sched_1_employer_availability_after_start` |
| FP-SCHED-2 | Booking eligibility (owner, employer match, `Interviewing`, future & free slot, no prior booking); booking survives status change | `app/services/scheduling.py` | `tests/unit/test_scheduling.py::test_fp_sched_2_eligible_booking`; `tests/unit/test_scheduling.py::test_fp_sched_2_ineligible_booking`; `tests/unit/test_scheduling.py::test_fp_sched_2_booking_survives_status_change` |
| FP-SCHED-3 | Atomic booking; race loser gets 409 `Slot already booked`; exactly one booking remains | `app/services/scheduling.py`, `app/db.py` (`BEGIN IMMEDIATE` + `UNIQUE`) | `tests/unit/test_scheduling.py::test_fp_sched_3_conflict_contract`; `tests/unit/test_scheduling.py::test_fp_sched_3_http_conflict_status_and_message` |
| FP-SEC-1 | Object-ID changes do not bypass authorization (resume/application, foreign job edit GET+POST/applicants, booking with foreign application) | ownership checks in `app/services/profiles.py`, `app/services/jobs.py` (`get_owned_job`), `app/services/applications.py`, `app/services/scheduling.py` | `tests/unit/test_security.py::test_fp_sec_1_candidate_cannot_access_other_resume_or_application`; `tests/unit/test_security.py::test_fp_sec_1_employer_cannot_modify_others_job_or_read_applicants`; `tests/unit/test_security.py::test_fp_sec_1_candidate_cannot_book_with_others_application` |
| FP-SEC-2 | Parameterized SQL; metacharacters stay bound values | `app/db.py` and all service queries (`?` placeholders) | `tests/unit/test_security.py::test_fp_sec_2_sql_metacharacters_stay_bound` |
| FP-SEC-3 | User text escaped in HTML; `<script>` never executable | Jinja2 autoescape (`app/templates/`), `app/security.py::escape_html` | `tests/unit/test_security.py::test_fp_sec_3_script_tag_is_escaped` |
| FP-SEC-4 | No real secrets/personal data; isolated test doubles; placeholder `.env.example` | `tests/conftest.py` (per-test SQLite file), `.env.example` | `tests/unit/test_security.py::test_fp_sec_4_test_isolation_and_no_secrets`; evidence: repository contains only `demo.local` demo data |
| FP-PROC-1 | Living specification matching the graded commit | `SPEC.md` | Evidence: `SPEC.md` sections map 1:1 to this implementation (architecture, data model, authz, routes, UI, matching, booking transaction, security) |
| FP-DOC-1 | Installation from clean checkout incl. Docker | `INSTALL.md`, `Dockerfile` | Evidence: `INSTALL.md` lists versions, install/migrate/seed/run/test + `docker build`/`docker run` commands and troubleshooting |
| FP-DOC-2 | Repository README contents and mapping table | `README.md` | Evidence: this document |
| FP-DOC-3 | One command resets + seeds the required dataset (incl. two jobs with required skills + the empty-skill example-4 carrier) | `app/seed.py`, `manage.py seed` | `tests/unit/test_seed.py::test_fp_doc_3_deterministic_seed_dataset` |
| FP-TEST-1 | Complete unit-test suite, one noninteractive command | `tests/unit/`, `tests/conftest.py` | Evidence: `python -m pytest tests/unit -q` (all named tests above cover every functional requirement plus the FP-TEST-1 bullet list) |
| FP-SUB-1 | Permanent commit URL on `main` + Dockerfile builds the complete environment | `Dockerfile`, `INSTALL.md` | Evidence: single-image Docker build with no runtime downloads; submit the permanent commit URL at the graded commit (course-site submission link) |

## Document Index

| Document | Purpose |
|---|---|
| [`README.md`](README.md) | Product overview, quick start, demo accounts, requirement–test mapping |
| [`SPEC.md`](SPEC.md) | Architecture, data model, authorization design, routes, UI, matching contract, booking transaction, security controls |
| [`INSTALL.md`](INSTALL.md) | Prerequisites, install/migrate/seed/run/test commands, Docker build and start, troubleshooting |
| [`requirements.txt`](requirements.txt) / [`requirements.lock`](requirements.lock) | Dependencies (direct and locked) |
| [`Dockerfile`](Dockerfile) | Complete runnable environment (app + tests, SQLite included) |
| [`manage.py`](manage.py) | `init-db`, `seed`, `run` commands |
| [`tests/unit/`](tests/unit/) | Student-written unit tests for every functional requirement |
| [`.github/workflows/ci.yml`](.github/workflows/ci.yml) | CI: runs the unit-test suite on every push/PR |
| [`.github/ISSUE_TEMPLATE/audit_bug_report.yml`](.github/ISSUE_TEMPLATE/audit_bug_report.yml) | Required audit issue form (peer review) |
| [`.github/labels.yml`](.github/labels.yml) | Audit label set (import into repository labels) |

## Known Limitations

- **FP-MATCH-2 (optional AI enhancement) is not implemented** — marked `N/A`.
  The core system therefore needs no LLM credentials and no fake-LLM fallback.
- SQLite is the persistent relational database: ideal for local grading and the
  single-container environment; a multi-writer production deployment would move
  to PostgreSQL (the booking transaction pattern transfers directly).
- Resumes are raw text (PDF upload/extraction is optional in FP-CAN-1 and not
  implemented). Resume text is never an input to matching, per FP-MATCH-1.
- All times are **UTC** (ISO-8601 `Z` storage, `YYYY-MM-DD HH:MM UTC` display).
  A production UI would localize display to the viewer's timezone.
- Without `SECRET_KEY` set, session keys are generated at process start and
  sessions expire on restart (see `INSTALL.md`).
- Job deletion is a hard delete permitted only when the job has no applications
  and no interview slots (FP-EMP-2); deleted jobs leave no candidate-visible
  residue.
