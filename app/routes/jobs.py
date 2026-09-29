"""Job detail, applying, and interview booking routes (FP-CAN-2, FP-CAN-3, FP-SCHED-2)."""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app.errors import ValidationError
from app.routes.helpers import current_user_id, login_required, role_required
from app.services import applications as applications_service
from app.services import jobs as jobs_service
from app.services import scheduling as scheduling_service

bp = Blueprint("jobs", __name__)


@bp.route("/jobs/<int:job_id>")
@login_required
def detail(job_id: int):
    job = jobs_service.get_job(job_id)
    user_id = current_user_id()
    applied = bool(user_id) and applications_service.has_applied(user_id, job_id)
    return render_template("jobs/detail.html", job=job, applied=applied)


@bp.route("/jobs/<int:job_id>/apply", methods=("POST",))
@role_required("Candidate")
def apply(job_id: int):
    applications_service.apply_to_job(current_user_id(), job_id)
    flash("Application submitted.", "success")
    return redirect(url_for("candidate.applications"))


@bp.route("/bookings", methods=("POST",))
@role_required("Candidate")
def create_booking():
    try:
        application_id = int(request.form.get("application_id", ""))
        slot_id = int(request.form.get("slot_id", ""))
    except ValueError:
        raise ValidationError("Invalid application or slot")
    scheduling_service.book_slot(current_user_id(), application_id, slot_id)
    flash("Interview booked.", "success")
    return redirect(url_for("candidate.application_detail", application_id=application_id))
