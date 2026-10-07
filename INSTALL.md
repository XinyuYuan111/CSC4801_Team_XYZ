# Installation Guide — TalentMatch

Everything below works from a clean checkout with no paid credentials and no
undocumented commands (FP-DOC-1). All application times are **UTC**.

## Prerequisites and Versions

| Tool | Version used |
|---|---|
| Python | 3.12.x (3.12.11 in Docker; 3.12+ works locally) |
| pip | bundled with Python (≥ 24) |
| Docker | 24+ with Docker Engine/ Desktop (only for the Docker path) |

No external database server is required: the persistent relational database is
SQLite (Python standard library).

## Dependency Installation

```bash
python -m venv .venv
```

- Windows (PowerShell): `.venv\Scripts\Activate.ps1`
- Windows (cmd): `.venv\Scripts\activate.bat`
- macOS / Linux: `source .venv/bin/activate`

```bash
python -m pip install -r requirements.txt
```

`requirements.txt` includes `requirements.lock`, which pins every direct and
transitive runtime/test version (Flask 3.1, waitress 3.0, pytest 8.4, …).

## Environment Variables

All optional. The app does **not** auto-load `.env` files; export them in your
shell (or Docker `-e`) if you want to override defaults. `.env.example` contains
placeholders only.

| Variable | Default | Meaning |
|---|---|---|
| `SECRET_KEY` | generated at startup | Flask session signing key. Without it, sessions expire on every restart. |
| `DATABASE` | `data/app.sqlite3` (in Docker: `/app/data/app.sqlite3`) | Path to the SQLite database file (parent directory is created automatically). |
| `PORT` | `8080` | HTTP port for `python manage.py run` / `python run.py`. |

## Database Setup and Migrations

Schema creation is idempotent (`CREATE TABLE IF NOT EXISTS`); it only creates
missing tables, never alters existing ones, and there is no separate migration
history to run.

```bash
python manage.py init-db
```

It is safe to run any time. To point at another database file:
`DATABASE=/path/to/app.sqlite3 python manage.py init-db`.

**After a pull that changes the schema in `app/db.py`** (for example a
constraint or foreign-key change such as `CASCADE` to `RESTRICT`), `init-db`
alone leaves an existing database file on the old shape. Recreate the schema
with `python manage.py seed` (drops and recreates all tables), or delete
`data/app.sqlite3` and run `init-db` again.

## Demo Data and Reset Command

One documented command **resets and seeds** the local database (FP-DOC-3):

```bash
python manage.py seed
```

This drops all tables, recreates the schema, and inserts the deterministic demo
dataset (two employers, three candidates, two jobs **with** required skills plus
one empty-skill job carrying FP-MATCH-1 example 4, the four matching examples as
literal skill pairs, applications covering all four statuses, and future
interview slots — Alice and Bob are both `Interviewing` on the same job and can
race for the same available slot). Slot start times are "tomorrow at
15:00/16:00/17:00 UTC" relative to seed time so they are always in the future;
everything else is constant.

**Local/demo credentials only** (reserved `demo.local` domain — never real
accounts):

| Email | Password | Role |
|---|---|---|
| `alice@demo.local` | `DemoPass123!` | Candidate (Python, SQL) |
| `bob@demo.local` | `DemoPass123!` | Candidate (Python) |
| `cara@demo.local` | `DemoPass123!` | Candidate (Rust) |
| `ana@demo.local` | `DemoPass123!` | Employer (Acme Corp) |
| `ben@demo.local` | `DemoPass123!` | Employer (Globex Inc) |

## Docker Build

From the repository root (no secrets or extra steps needed):

```bash
docker build -t team-xyz .
```

The image contains the application **and** the test suite; nothing is downloaded
at run time. It does not bundle a database volume (SQLite lives at
`/app/data/app.sqlite3` inside the container; re-seed after `docker rm`).

## Docker Startup

```bash
docker run -d --name team-xyz -p 127.0.0.1:8080:8080 team-xyz
```

On start the container initializes the schema and serves with waitress. Then:

```bash
docker exec team-xyz python manage.py seed                 # reset + demo data
docker exec team-xyz python -m pytest tests/unit -q        # unit tests
```

Open `http://127.0.0.1:8080` and log in with a demo account above. To persist
data across container recreation, mount a volume: add
`-v team-xyz-data:/app/data`. To reset everything: `docker rm -f team-xyz` and
start again, then re-seed. Optional: `-e SECRET_KEY=...` for stable sessions.

## Local Development

```bash
python manage.py init-db
python manage.py seed
python manage.py run            # http://127.0.0.1:8080
```

`run` uses waitress; `python run.py` is equivalent. The development flow for
tests does not need the server at all.

## Running Unit Tests

One command, non-interactive, from the repository root; exits nonzero on any
failure:

```bash
python -m pytest tests/unit -q
```

Tests use an isolated SQLite database per test (never the demo database) and
call no third-party services. CI runs exactly this command
(`.github/workflows/ci.yml`).

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: app` | Run commands from the repository root (the `app/` package must be importable), or set `PYTHONPATH=.` |
| `sqlite3.OperationalError: unable to open database file` | Ensure the directory of `DATABASE` exists and is writable (the app creates it for the default path; custom paths need a writable parent) |
| `database is locked` | Stop other writers (e.g., a running server using the same `DATABASE` file while seeding); SQLite allows one writer at a time |
| Logged out after a server restart | Expected without `SECRET_KEY`; set `SECRET_KEY` in the environment for stable sessions |
| Port 8080 already in use | `PORT=8081 python manage.py run` (and map the same port in Docker `-p`) |
| Windows PowerShell: script execution denied for the venv activate | `powershell -ExecutionPolicy Bypass` or use `cmd` activation |
| Booking form shows "No available slots" | Slots must be future + unbooked and belong to the application's employer; re-run `python manage.py seed` for the demo slots (created for tomorrow UTC) |
| Docker seed re-seeds on every `docker exec ... seed` | Intended: `seed` is a full reset (FP-DOC-3). Data persistence across resets is not expected |
