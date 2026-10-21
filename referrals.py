from datetime import datetime, date

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, current_app
from flask_login import login_required, current_user

from models import db, Referral, Patient, MDTCase, REFERRAL_STATUS, DECISIONS
from core import team_required, audit, parse_date, ensure_candidate
from patients import get_or_create_patient
from schemas import REFERRAL_CLINICAL, parse_section

referrals_bp = Blueprint("referrals", __name__, url_prefix="/referrals")


def _can_see(r):
    return current_user.is_team or r.referring_user_id == current_user.id


@referrals_bp.route("")
@login_required
def listing():
    q = Referral.query
    if not current_user.is_team:
        q = q.filter_by(referring_user_id=current_user.id)
    st = request.args.get("status")
    if st in REFERRAL_STATUS:
        q = q.filter_by(status=st)
    return render_template("referrals.html", rows=q.order_by(Referral.created_at.desc()).all(), st=st)


@referrals_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    if request.method == "POST":
        f = request.form
        p, created = get_or_create_patient(f)
        if not p:
            flash("Civil ID and patient name are required.", "error")
        elif not f.get("primary_diagnosis", "").strip() or not f.get("reason", "").strip():
            flash("Primary diagnosis and reason for referral are required.", "error")
        else:
            if p.date_of_birth and (p.age is not None) and p.age < 18:
                flash("The LTU serves adults aged 18 and above. Paediatric referrals are outside the unit's scope.", "error")
                return render_template("referral_new.html", sections=REFERRAL_CLINICAL, form=f), 400
            r = Referral(patient_id=p.id, referring_user_id=current_user.id, institution=f.get("institution") or current_user.hospital,
                         referring_physician=f.get("referring_physician") or current_user.full_name, referral_date=parse_date(f.get("referral_date")) or date.today(),
                         primary_diagnosis=f["primary_diagnosis"].strip(), reason=f["reason"].strip())
            for key, _t, fields in REFERRAL_CLINICAL:
                r.set_section(key, parse_section(fields, f, key + "__"))
            db.session.add(r)
            ensure_candidate(p, "evaluation", r.primary_diagnosis)
            db.session.flush()
            audit("referral_created", p.id, f"referral {r.id}")
            db.session.commit()
            flash("Referral submitted to the Lung Transplant Unit.", "success")
            return redirect(url_for("referrals.view", rid=r.id))
        return render_template("referral_new.html", sections=REFERRAL_CLINICAL, form=f), 400
    return render_template("referral_new.html", sections=REFERRAL_CLINICAL, form={})


@referrals_bp.route("/<int:rid>")
@login_required
def view(rid):
    r = db.session.get(Referral, rid) or abort(404)
    if not _can_see(r):
        abort(403)
    mdt = MDTCase.query.filter_by(referral_id=r.id, status="final").order_by(MDTCase.finalised_at.desc()).first()
    sent_ok = bool(r.decision_sent_at)
    # a referring physician only sees the decision once the team has marked it as communicated
    show_decision = mdt if (current_user.is_team or sent_ok) else None
    if current_user.is_team:
        audit("referral_viewed", r.patient_id, f"referral {r.id}")
        db.session.commit()
    return render_template("referral_view.html", r=r, mdt=show_decision, sections=REFERRAL_CLINICAL, data=r.get_data("clinical"))


@referrals_bp.route("/<int:rid>/status", methods=["POST"])
@team_required
def status(rid):
    r = db.session.get(Referral, rid) or abort(404)
    new = request.form.get("status")
    if new in REFERRAL_STATUS:
        r.status = new
    if request.form.get("mark_sent"):
        r.decision_sent_at = datetime.utcnow()
        r.status = "decided"
    audit("referral_status", r.patient_id, f"referral {r.id} -> {r.status}")
    db.session.commit()
    return redirect(url_for("referrals.view", rid=r.id))


@referrals_bp.route("/<int:rid>/letter")
@login_required
def letter(rid):
    """Printable written decision (IMPL-01 4.4: communicated within 5 working days)."""
    r = db.session.get(Referral, rid) or abort(404)
    if not _can_see(r):
        abort(403)
    mdt = MDTCase.query.filter_by(referral_id=r.id, status="final").order_by(MDTCase.finalised_at.desc()).first()
    if not mdt or (not current_user.is_team and not r.decision_sent_at):
        abort(404)
    return render_template("referral_letter.html", r=r, mdt=mdt, listing=mdt.get_data("listing"))
