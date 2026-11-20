"""Employer-facing routes: company, jobs, applicants, slots (FP-EMP-1..3, FP-SCHED-1)."""

import re
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.errors import ValidationError
from app.routes.helpers import current_user_id, role_required, submitted_skill_tags
from app.services import applications as applications_service
from app.services import jobs as jobs_service
from app.services import profiles as profiles_service
from app.services import scheduling as scheduling_service
from app.timeutils import UTC, parse_iso, plus_minutes, to_iso, utc_now

bp = Blueprint("employer", __name__)


@bp.route("/company", methods=("GET", "POST"))
@role_required("Employer")
def company():
    user_id = current_user_id()
    if request.method == "POST":
        try:
            profiles_service.update_company(
                user_id,
                company_name=request.form.get("company_name", ""),
                description=request.form.get("description", ""),
            )
        except ValidationError as exc:
            return render_template(
                "employer/company.html",
                company=profiles_service.get_company(user_id),
                error=exc.message,
            ), exc.status
        flash("Company profile updated.", "success")
        return redirect(url_for("employer.company"))
    return render_template(
        "employer/company.html", company=profiles_service.get_company(user_id), error=None
    )


@bp.route("/employer/jobs")
@role_required("Employer")
def jobs():
    rows = jobs_service.list_employer_jobs(current_user_id())
    return render_template("employer/jobs.html", jobs=rows)


@bp.route("/employer/jobs/new", methods=("GET", "POST"))
@role_required("Employer")
def new_job():
    if request.method == "POST":
        tags = submitted_skill_tags()
        try:
            jobs_service.create_job(
                current_user_id(),
                title=request.form.get("title", ""),
                description=request.form.get("description", ""),
                skills_text=request.form.get("skill_draft", ""),
                skill_items=tags,
            )
        except ValidationError as exc:
            return render_template("employer/job_form.html", job=None, submitted_tags=tags, error=exc.message), exc.status
        flash("Job created.", "success")
        return redirect(url_for("employer.jobs"))
    return render_template("employer/job_form.html", job=None, error=None)


@bp.route("/jobs/<int:job_id>/edit", methods=("GET", "POST"))
@role_required("Employer")
def edit_job(job_id: int):
    if request.method == "POST":
        tags = submitted_skill_tags()
        try:
            jobs_service.update_job(
                current_user_id(),
                job_id,
                title=request.form.get("title", ""),
                description=request.form.get("description", ""),
                skills_text=request.form.get("skill_draft", ""),
                skill_items=tags,
            )
        except ValidationError as exc:
            return render_template(
                "employer/job_form.html",
                job=jobs_service.get_owned_job(current_user_id(), job_id),
                submitted_tags=tags,
                error=exc.message,
            ), exc.status
        flash("Job updated.", "success")
        return redirect(url_for("employer.jobs"))
    return render_template(
        "employer/job_form.html",
        job=jobs_service.get_owned_job(current_user_id(), job_id),
        error=None,
    )


@bp.route("/jobs/<int:job_id>/delete", methods=("POST",))
@role_required("Employer")
def delete_job(job_id: int):
    jobs_service.delete_job(current_user_id(), job_id)
    flash("Job deleted.", "success")
    return redirect(url_for("employer.jobs"))


@bp.route("/jobs/<int:job_id>/applicants")
@role_required("Employer")
def applicants(job_id: int):
    job = jobs_service.get_owned_job(current_user_id(), job_id)  # 404 / 403 first
    rows = applications_service.list_applicants(current_user_id(), job_id)
    return render_template("employer/applicants.html", job=job, applicants=rows)


@bp.route("/applications/<int:application_id>/status", methods=("POST",))
@role_required("Employer")
def set_status(application_id: int):
    detail = applications_service.set_status(
        current_user_id(), application_id, request.form.get("status", "")
    )
    flash("Application status updated.", "success")
    return redirect(url_for("employer.applicants", job_id=detail["job_id"]))


@bp.route("/employer/slots", methods=("GET",))
@role_required("Employer")
def slots():
    return _render_slots()


def _render_slots(error=None):
    rows = scheduling_service.list_slots_for_employer(current_user_id())
    owned_jobs = jobs_service.list_employer_jobs(current_user_id())
    now = utc_now()
    return render_template(
        "employer/slots.html", slots=rows, jobs=owned_jobs, error=error,
        now_ms=int(now.timestamp() * 1000),
        first_date=(now + timedelta(minutes=1)).date().isoformat(),
    )


def _submitted_slot_start():
    if "slot_date" not in request.form:
        return parse_iso(request.form.get("start_utc", ""))
    date = request.form["slot_date"]
    hour = request.form.get("slot_hour", "")
    minute = request.form.get("slot_minute", "")
    value = f"{date} {hour}:{minute}"
    message = "Enter a valid date in yyyy/mm/dd format and select an hour and minute (UTC)."
    if not re.fullmatch(r"[0-9]{4}/[0-9]{2}/[0-9]{2} [0-9]{2}:[0-9]{2}", value):
        raise ValidationError(message)
    try:
        return datetime.strptime(value, "%Y/%m/%d %H:%M").replace(tzinfo=UTC)
    except ValueError as exc:
        raise ValidationError(message) from exc


@bp.route("/employer/slots", methods=("POST",))
@role_required("Employer")
def create_slot():
    job_id = request.form.get("job_id", type=int)
    try:
        if job_id is None:
            raise ValidationError("Select a job for this slot")
        # The form collects a start time only; the end is always start + 30 minutes.
        start = _submitted_slot_start()
        end_iso = plus_minutes(to_iso(start), 30)
        scheduling_service.create_slot(current_user_id(), job_id, to_iso(start), end_iso)
    except (ValidationError, ValueError, OverflowError) as exc:
        message = exc.message if isinstance(exc, ValidationError) else "Times must be ISO-8601 UTC, e.g. 2026-05-01T15:00:00Z"
        return _render_slots(message), 400
    flash("Slot created.", "success")
    return redirect(url_for("employer.slots"))


@bp.route("/slots/<int:slot_id>/delete", methods=("POST",))
@role_required("Employer")
def delete_slot(slot_id: int):
    scheduling_service.delete_slot(current_user_id(), slot_id)
    flash("Slot deleted.", "success")
    return redirect(url_for("employer.slots"))
