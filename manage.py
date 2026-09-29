"""Management commands: init-db, seed, run.

Usage (from the repository root):

    python manage.py init-db
    python manage.py seed      # reset + deterministic demo data (FP-DOC-3)
    python manage.py run       # serve on PORT (default 8080) via waitress
"""

import os
import sys

import click


@click.group()
def cli():
    """TalentMatch management commands."""


@cli.command("init-db")
def init_db_command():
    """Create the database schema (idempotent)."""
    from app import create_app
    from app.db import get_db, init_db

    app = create_app()
    with app.app_context():
        init_db()
        get_db()
    click.echo(f"Database initialized at {app.config['DATABASE']}")


@cli.command("seed")
def seed_command():
    """Reset the database and insert deterministic demo data (FP-DOC-3)."""
    from app import create_app
    from app.seed import seed_demo_data

    app = create_app()
    with app.app_context():
        ids = seed_demo_data()
    click.echo("Demo data seeded (local/demo credentials only):")
    click.echo("  alice@demo.local / DemoPass123!  Candidate (skills: Python, SQL)")
    click.echo("  bob@demo.local   / DemoPass123!  Candidate (skills: Python)")
    click.echo("  cara@demo.local  / DemoPass123!  Candidate (skills: Rust)")
    click.echo("  ana@demo.local   / DemoPass123!  Employer  (Acme Corp)")
    click.echo("  ben@demo.local   / DemoPass123!  Employer  (Globex Inc)")
    click.echo(f"  jobs={ids['jobs']} applications={len(ids['applications'])} slots={ids['slots']}")


@cli.command("run")
@click.option("--host", default="0.0.0.0", show_default=True)
@click.option("--port", default=None, type=int, help="Defaults to $PORT or 8080.")
def run_command(host, port):
    """Serve the application with waitress (single-process WSGI server)."""
    from waitress import serve

    from app import create_app

    app = create_app()
    port = port or app.config["PORT"]
    click.echo(f"Serving on http://{host}:{port} (database: {app.config['DATABASE']})")
    serve(app, host=host, port=port)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    sys.exit(cli())
