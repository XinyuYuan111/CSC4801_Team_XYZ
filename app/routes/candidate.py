"""Candidate-facing routes: dashboard, profile, private resume, applications (FP-CAN-1..3)."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.errors import ValidationError
from app.routes.helpers import current_user_id, role_required
from app.services import applications as applications_service
from app.services import jobs as jobs_service
from app.services import profiles as profiles_service
from app.services import scheduling as scheduling_service

bp = Blueprint("candidate", __name__)


@bp.route("/dashboard")
@role_required("Candidate")
def dashboard():
    rows = jobs_service.list_jobs_with_scores(current_user_id())
    return render_template("candidate/dashboard.html", jobs=rows)


@bp.route("/profile", methods=("GET", "POST"))
@role_required("Candidate")
def profile():
    user_id = current_user_id()
    if request.method == "POST":
        try:
            profiles_service.update_candidate_profile(
                user_id,
                display_name=request.form.get("display_name", ""),
                skills_text=request.form.get("skills", ""),
            )
        except ValidationError as exc:
            return render_template(
                "candidate/profile.html",
                profile=profiles_service.get_candidate_profile(user_id),
                error=exc.message,
            ), exc.status
        flash("Profile updated.", "success")
        return redirect(url_for("candidate.profile"))
    return render_template(
        "candidate/profile.html",
        profile=profiles_service.get_candidate_profile(user_id),
        error=None,
    )


@bp.route("/candidates/<int:candidate_id>/resume", methods=("GET",))
@role_required("Candidate")
def resume(candidate_id: int):
    # Object-level access: only the owning candidate may read (403/404 otherwise).
    text = profiles_service.read_resume(current_user_id(), candidate_id)
    return render_template("candidate/resume.html", candidate_id=candidate_id, resume_text=text)


@bp.route("/candidates/<int:candidate_id>/resume", methods=("POST",))
@role_required("Candidate")
def replace_resume(candidate_id: int):
    profiles_service.replace_resume(current_user_id(), candidate_id, request.form.get("resume_text", ""))
    flash("Resume replaced.", "success")
    return redirect(url_for("candidate.resume", candidate_id=candidate_id))


@bp.route("/applications")
@role_required("Candidate")
def applications():
    rows = applications_service.list_my_applications(current_user_id())
    return render_template("candidate/applications.html", applications=rows)


@bp.route("/applications/<int:application_id>")
@role_required("Candidate")
def application_detail(application_id: int):
    detail = applications_service.get_application_for_candidate(current_user_id(), application_id)
    slots = []
    if detail["status"] == "Interviewing" and detail["booking"] is None:
        slots = scheduling_service.list_available_slots(detail["employer_id"])
    return render_template(
        "candidate/application_detail.html", application=detail, slots=slots
    )
