"""Registration, login, and logout routes (FP-AUTH-1)."""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from app.errors import AppError
from app.routes.helpers import clear_session, current_user, login_required
from app.services import auth as auth_service


def _start_session(user_id: int):
    """Log a user in while keeping the CSRF token bound to this browser session."""
    csrf = session.get("csrf_token")
    session.clear()
    session["user_id"] = user_id
    session["csrf_token"] = csrf


bp = Blueprint("auth", __name__)


@bp.route("/")
def home():
    user = current_user()
    if user is None:
        return redirect(url_for("auth.login"))
    if user["role"] == "Employer":
        return redirect(url_for("employer.jobs"))
    return redirect(url_for("candidate.dashboard"))


@bp.route("/register", methods=("GET", "POST"))
def register():
    if request.method == "POST":
        role = request.form.get("role", "")
        try:
            user_id = auth_service.register_user(
                email=request.form.get("email", ""),
                password=request.form.get("password", ""),
                role=role,
                display_name=request.form.get("display_name", ""),
                company_name=request.form.get("company_name", ""),
            )
        except AppError as exc:
            return render_template("auth/register.html", error=exc.message), exc.status
        _start_session(user_id)
        flash("Account created. You are now logged in.", "success")
        if role == "Employer":
            return redirect(url_for("employer.jobs"))
        return redirect(url_for("candidate.dashboard"))
    return render_template("auth/register.html", error=None)


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        user = auth_service.authenticate(request.form.get("email", ""), request.form.get("password", ""))
        if user is None:
            # 401: unknown email and wrong password are indistinguishable.
            return render_template("auth/login.html", error="Invalid email or password"), 401
        _start_session(user["id"])
        flash("Logged in.", "success")
        if user["role"] == "Employer":
            return redirect(url_for("employer.jobs"))
        return redirect(url_for("candidate.dashboard"))
    return render_template("auth/login.html", error=None)


@bp.route("/logout", methods=("POST",))
@login_required
def logout():
    clear_session()
    flash("Logged out.", "success")
    return redirect(url_for("auth.login"))
