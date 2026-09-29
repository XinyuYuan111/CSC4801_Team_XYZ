"""Flask application factory (FP-ARCH-1).

Server-rendered UI over a service layer that enforces every business rule and
authorization decision. Error pages carry the FP-AUTH-3 status contract.
"""

import os
import secrets
from pathlib import Path

from flask import Flask, g, render_template, request, session

from app import db as db_module
from app.errors import AppError, AuthorizationError
from app.security import csrf_token_valid, new_csrf_token
from app.timeutils import format_display

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app(test_config=None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
        DATABASE=os.environ.get("DATABASE") or str(BASE_DIR / "data" / "app.sqlite3"),
        PORT=int(os.environ.get("PORT", "8080")),
    )
    if test_config:
        app.config.update(test_config)

    db_module.init_app(app)

    from app.routes.auth import bp as auth_bp
    from app.routes.candidate import bp as candidate_bp
    from app.routes.employer import bp as employer_bp
    from app.routes.jobs import bp as jobs_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(candidate_bp)
    app.register_blueprint(employer_bp)
    app.register_blueprint(jobs_bp)

    @app.before_request
    def load_user_and_csrf():
        if "csrf_token" not in session:
            session["csrf_token"] = new_csrf_token()
        g.user = None
        user_id = session.get("user_id")
        if user_id is not None:
            row = db_module.get_db().execute(
                "SELECT id, email, role FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            if row is not None:
                g.user = dict(row)
        if request.method == "POST" and not csrf_token_valid(
            session.get("csrf_token", ""), request.form.get("csrf_token", "")
        ):
            raise AuthorizationError("Invalid or missing CSRF token")

    @app.errorhandler(AppError)
    def handle_app_error(error: AppError):
        return render_template("errors/error.html", error=error), error.status

    @app.errorhandler(404)
    def handle_404(_error):
        return render_template("errors/error.html", error=AppError("Not found", status=404)), 404

    @app.errorhandler(405)
    def handle_405(_error):
        return render_template("errors/error.html", error=AppError("Method not allowed", status=405)), 405

    @app.template_filter("utc_display")
    def utc_display(value):
        return format_display(value) if value else ""

    @app.context_processor
    def inject_globals():
        from flask import session as flask_session

        return {
            "current_user": g.get("user"),
            "csrf_token": lambda: flask_session.get("csrf_token", ""),
        }

    return app
