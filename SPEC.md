# Project Specification — TalentMatch

Living specification for the CSC4801 recruiting and candidate matching system.
This document matches the graded commit; the requirement–test mapping lives in
[`README.md`](README.md) (FP-DOC-2), not here (FP-PROC-1).

## Product Scope

TalentMatch is a locally runnable full-stack application (FP-ARCH-1):

- browser-based UI (server-rendered HTML),
- Flask backend enforcing all business rules and authorization,
- persistent relational database (SQLite).

Exactly two application roles exist: `Candidate` and `Employer` (FP-AUTH-1).
Candidates: profile + technical skills + private raw-text resume; ranked job
recommendations; apply-once applications; interview slot booking. Employers:
company profile; job postings with required skills; applicant management with
four statuses; 30-minute interview availability slots. No LLM is used anywhere
(FP-MATCH-2 is not implemented).

## Architecture

```
Browser (Jinja2 HTML forms/pages)
   │  HTTP (cookies: signed session + CSRF token in forms)
   ▼
Flask routes (app/routes/)          ← thin: parse input, render outcomes
   │  raise typed errors → HTTP 400/401/403/404/409 pages (app/errors.py)
   ▼
Service layer (app/services/)       ← ALL business rules + authorization
   │  parameterized SQL only (FP-SEC-2)
   ▼
SQLite (app/db.py)                  ← schema, BEGIN IMMEDIATE transactions
```

Shared libraries: `app/matching.py` (the single matching implementation),
`app/security.py` (password hashing, HTML escaping, CSRF), `app/timeutils.py`
(UTC time handling). Entry points: `run.py` (WSGI app object), `manage.py`
(`init-db` / `seed` / `run` commands), `Dockerfile` (single complete image).

## Data Model and Relationships

Schema DDL: `app/db.py` (`SCHEMA`). All timestamps are UTC ISO-8601
(`YYYY-MM-DDTHH:MM:SSZ`).

| Table | Columns (key parts) | Constraints / relationships |
|---|---|---|
| `users` | `id`, `email`, `password_hash`, `role`, `created_at` | `email` UNIQUE (stored lowercased → case-insensitive identity); `role IN ('Candidate','Employer')` |
| `candidate_profiles` | `user_id`, `display_name`, `resume_text` | 1:1 `users.id` (candidate); `resume_text` default `''` |
| `candidate_skills` | `user_id`, `skill` | PK `(user_id, skill)` → 1:N skills per candidate, deduplicated |
| `company_profiles` | `user_id`, `company_name`, `description` | 1:1 `users.id` (employer) |
| `jobs` | `id`, `employer_id`, `title`, `description`, `created_at` | N:1 `users.id` (employer owner) |
| `job_skills` | `job_id`, `skill` | PK `(job_id, skill)` → 1:N required skills per job (may be empty) |
| `applications` | `id`, `job_id`, `candidate_id`, `status`, `created_at` | `UNIQUE (job_id, candidate_id)` enforces apply-once; `status IN ('Pending','Interviewing','Rejected','Accepted')` |
| `interview_slots` | `id`, `job_id`, `employer_id`, `start_utc`, `end_utc`, `created_at` | N:1 `jobs.id`; `employer_id` is the slot owner (must equal the job's employer at creation); `CHECK (end_utc > start_utc)` |
| `bookings` | `id`, `slot_id`, `application_id`, `created_at` | `UNIQUE (slot_id)` one booking per slot; `UNIQUE (application_id)` one booking per application — the FP-SCHED-3 DB backstop |

Deletion rules: a job may be deleted only when it has **no applications and no
interview slots** (FP-EMP-2); otherwise `409` and nothing changes. Slots are
deletable only while unbooked (FP-SCHED-1). A booking row survives status
changes on its application and keeps the slot unavailable (FP-SCHED-2).

## Authentication and Authorization

**Authentication (FP-AUTH-1, FP-AUTH-2).** Registration creates a user with
email (unique identifier, stored lowercased), password, and one of the two
roles. Passwords are stored with `werkzeug.security.generate_password_hash`
(salted scrypt/PBKDF2 — an established password-hashing function). Verification
uses `check_password_hash`; unknown email and wrong password are
indistinguishable (`401 Invalid email or password`). Password hashes are never
returned by any code path or rendered in any template. Sessions are signed
Flask session cookies containing only `user_id` and role lookup — logout clears
the session. Unauthenticated access:

- `GET` of a protected page → `302` redirect to `/login` (the FP-AUTH-3
  "redirect to login" option);
- any other method → `401 Unauthorized` page.

**Authorization (FP-AUTH-3, FP-SEC-1).** Every protected operation is enforced
in the service layer on the server (hiding buttons is never the control). The
observable contract:

| Situation | Outcome |
|---|---|
| Unauthenticated | `401` (or login redirect for GET pages) |
| Authenticated, wrong role or not the owner | `403 Forbidden` |
| Object missing that the caller could otherwise access | `404 Not Found` |
| Conflicting state (duplicate application, booked slot, job with dependents, booking race loser) | `409 Conflict` |
| Invalid input | `400` |

Ownership map: resumes are readable/replaceable only by their owning candidate
(any other candidate or employer gets `403` on direct URL); applications are
visible to their candidate and to the employer owning the job, and only that
employer may set status; jobs and their applicant lists are managed only by the
employer who owns the posting; slots are owned by the creating employer (tied to
one of their jobs); bookings require the caller to own the application.
Changing any object id in a URL or form must not bypass these checks — covered
by `tests/unit/test_security.py`.

## API Routes or Server Actions

All routes are HTML form/page endpoints (server actions). Methods not listed
return `405`.

### Auth (`app/routes/auth.py`)

| Route | Method | Who | Behavior |
|---|---|---|---|
| `/register` | GET, POST | public | Registration form; creates user + profile row and logs in |
| `/login` | GET, POST | public | Login form; `401` on bad credentials |
| `/logout` | POST | logged in | Clears session |

### Candidate (`app/routes/candidate.py`)

| Route | Method | Who | Behavior |
|---|---|---|---|
| `/dashboard` | GET | Candidate | All jobs with match scores, sorted desc (FP-CAN-2) |
| `/profile` | GET, POST | Candidate | View/edit own display name + skills |
| `/candidates/<cid>/resume` | GET | Candidate owner | View own resume (`403` others incl. employers, `404` missing) |
| `/candidates/<cid>/resume` | POST | Candidate owner | Replace own resume text |
| `/applications` | GET | Candidate | Own applications with job, employer, status, booking |
| `/applications/<id>` | GET | Candidate owner | Application detail; booking UI when `Interviewing` and unbooked (`403` other candidates) |
| `/applications/<id>` | GET | Employer owner | Same detail (service allows the job's employer) |

### Jobs & booking (`app/routes/jobs.py`)

| Route | Method | Who | Behavior |
|---|---|---|---|
| `/jobs/<id>` | GET | any logged-in | Job detail (title, company, description, skills) |
| `/jobs/<id>/apply` | POST | Candidate | Apply once; new application `Pending`; duplicate → `409` |
| `/bookings` | POST | Candidate | Book `application_id` + `slot_id`; FP-SCHED-2 eligibility; race loser → `409 Slot already booked` |

### Employer (`app/routes/employer.py`)

| Route | Method | Who | Behavior |
|---|---|---|---|
| `/company` | GET, POST | Employer | View/edit company profile |
| `/employer/jobs` | GET | Employer | Own job postings with applicant/slot counts |
| `/employer/jobs/new` | GET, POST | Employer | Create posting (title + description required; skills may be empty) |
| `/jobs/<id>/edit` | GET, POST | Employer owner | Edit own posting (`403` foreign) |
| `/jobs/<id>/delete` | POST | Employer owner | Delete; `409` if applications or slots exist |
| `/jobs/<id>/applicants` | GET | Employer owner | Applicants sorted by score with full rows (FP-EMP-3) |
| `/applications/<id>/status` | POST | Employer owner | Set `Pending/Interviewing/Rejected/Accepted` |
| `/employer/slots` | GET | Employer | Own slots with booked/available state |
| `/employer/slots` | POST | Employer | Create a future 30-minute slot for one owned job (form takes start; end = start + 30 min) |
| `/slots/<id>/delete` | POST | Employer owner | Delete unbooked slot; `409` if booked |

Every POST requires a valid session CSRF token (`403` otherwise).

## User Interface and Workflows

| Screen | Audience | Content |
|---|---|---|
| Login / Register | public | Email + password; role + display/company name on register |
| Job dashboard | Candidate | All jobs: score, title, company, required skills, description link |
| Job detail | both | Description + skills; candidate sees Apply (or "already applied"); owning employer sees Edit/Applicants |
| My profile | Candidate | Display name + skills editor (skills feed matching) |
| My resume | Candidate | Raw-text resume view/replace (private) |
| My applications | Candidate | Job, company, status, booking per application |
| Application detail | Candidate / owning employer | Job + employer + status + booking; booking form lists future unbooked slots of the application's employer when `Interviewing` |
| Company profile | Employer | Company name + description |
| My job postings | Employer | Own postings with counts; create/edit/delete/applicants |
| Applicants | Employer | Score, candidate, skills, status, booking; status selector per row |
| Interview slots | Employer | Create slot (job + UTC start), list with booked state, delete unbooked |

Workflow notes: a candidate applies once (duplicate POST → `409` error page);
the employer flips status to `Interviewing` to unlock booking; the candidate
books one slot from the application detail page; both sides then see the
booking. If the application later leaves `Interviewing`, the booking remains
linked and the slot remains unavailable.

## Matching Algorithm and Skill Storage

**Skill storage.** Free-text input (`Python, SQL`) is split on commas/newlines
and normalized: trim whitespace, lowercase, drop empties, drop duplicates
(`app/matching.py::parse_skills_text` / `normalize_skills`). Normalized skills
are stored one per row in `candidate_skills` and `job_skills` (PK-deduplicated)
so the matcher reads sets directly.

**Score (FP-MATCH-1 — the required formula).** `C` = normalized candidate skill
set, `R` = normalized required skill set. Resume text is **not** an input.

```text
score = 100                                      when |R| = 0
score = floor(100 * |C intersection R| / |R|)    otherwise
```

Integer floor division (`100 * inter // len(R)`), result always an integer
0–100. Candidate and employer views both call `app/matching.py::match_score` —
there is exactly one implementation. Sorting: candidate dashboard by score desc,
then case-insensitive job title, then job id; employer applicants by score desc,
then case-insensitive candidate display name, then candidate id
(`sort_jobs_for_candidate` / `sort_applicants_for_employer`).

## Interview Scheduling and Booking Transaction

**Slots (FP-SCHED-1).** Exact start/end UTC instants, always exactly 30 minutes,
always created in the future. One owner (the creating employer) and one job
posting (so job deletion correctly reports dependent interview slots — FP-EMP-2).
Creation rejects: malformed timestamps, end ≤ start, any duration other than 30
minutes, non-future start, foreign/missing job (`403`/`404`). Deletion rejects a
booked slot (`409`) and a foreign/missing slot (`403`/`404`). Availability
listings exclude booked and past slots.

**Booking eligibility (FP-SCHED-2).** `book_slot(candidate, application, slot)`
succeeds **iff** all of: the candidate owns the application (`403` otherwise);
the slot belongs to the employer of the application's job (`403` otherwise);
status is `Interviewing` (`409` otherwise); the slot is in the future and not
booked (`409`); and the application has no existing booking (`409`). Failures
change neither the slot nor the application. Success links the booking to the
application; it is visible to the candidate and the owning employer. Status
changes never unlink a booking.

**Transaction (FP-SCHED-3).** Booking runs in a SQLite `BEGIN IMMEDIATE`
transaction (`app/db.py::transaction(immediate=True)`), serializing concurrent
writers at the database, then re-checks eligibility and inserts. Two `UNIQUE`
constraints (`bookings.slot_id`, `bookings.application_id`) are the database
backstop: if a competing writer commits first, the insert raises
`IntegrityError`, which maps to `409 Conflict` with the exact message
`Slot already booked`. Race outcome: exactly one booking row remains; the loser
gets HTTP `409` and that message.

## Security Controls

| Control | Design |
|---|---|
| Password storage (FP-AUTH-2) | Salted established hash (werkzeug scrypt/PBKDF2); never plain text/reversible/fast-unsalted; hashes never leave the data layer |
| Server-side authorization (FP-AUTH-3) | Service-layer role + ownership checks on every operation; UI hiding is not a control; 401/403/404 contract above |
| Object access (FP-SEC-1) | Every object read/write re-checks ownership against the session user; unit-tested boundaries: cross-candidate resume/application, cross-employer job/applicants, booking with a foreign application |
| SQL injection (FP-SEC-2) | 100% parameterized queries (`?` placeholders) through `sqlite3`; no string-built SQL with user input; metacharacter unit test |
| XSS (FP-SEC-3) | All user text (profile, resume, company, job, search-like fields) rendered through Jinja2 autoescaping; no `\|safe` filters; `escape_html` helper for non-template paths; `<script>alert(1)</script>` unit test |
| CSRF | Per-session token required on every POST (defense in depth beyond the graded MUST set) |
| Secrets & test isolation (FP-SEC-4) | No real secrets/personal data in the repository (demo data uses `demo.local`); `.env.example` placeholders only; unit tests use per-test isolated SQLite files and never call third-party services |
| Sessions | Signed HttpOnly cookies; logout clears session; optional `SECRET_KEY` env var |

## Optional AI Features and Data Flow

**Not implemented** (FP-MATCH-2 marked `N/A` in the README mapping). No
user-controlled text is sent to any LLM or external service; there is no prompt,
no model key, and no AI data flow to document. The deterministic skill-overlap
score is the only ranking signal.

## Design Decisions and Limitations

- **Stack:** Python 3.12 / Flask 3.1 / SQLite / waitress — minimal dependency
  surface (the starter lockfile), easy clean-checkout grading, single Docker
  image with no external database container.
- **UTC everywhere:** documented unambiguous timezone (FP-SCHED-1); stored as
  ISO-8601 `Z`, displayed as `YYYY-MM-DD HH:MM UTC`. The slot form collects a
  start time interpreted as UTC and derives end = start + 30 minutes.
- **Slot → job linkage:** each slot belongs to one job posting and its employer.
  Booking eligibility uses the FP-SCHED-2 rule (slot's employer = application's
  employer). Because eligibility is defined as "if and only if" those five
  conditions hold, a candidate with an `Interviewing` application at employer E
  may book any eligible slot owned by E, including a slot created under a
  different posting of E; the UI offers the application's employer's slots.
- **Hard job delete** (no soft-delete flag): allowed only with zero
  applications and zero slots, so "current (not deleted)" jobs on the dashboard
  are exactly the rows in `jobs`.
- **409 semantics** (documented equivalent outcomes): duplicate application —
  `409 Application already submitted`; delete with dependents — `409 Job has
  applications or interview slots and cannot be deleted`; booked-slot deletion —
  `409 Cannot delete a booked slot`; booking conflicts — `409 Slot already
  booked` (required message), other ineligible bookings use `409` with the
  specific reason (`Application is not in Interviewing status`, `Slot is in the
  past`, `Application already has a booking`).
- **No pagination** on lists (course-scale data); no PDF resume extraction
  (optional in the requirements); no LLM (see above).
