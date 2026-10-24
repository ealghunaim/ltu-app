from datetime import date, timedelta

import hmac
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, current_app
from flask_login import login_required, current_user

from models import (db, Patient, Referral, MDTCase, Candidate, CandidateStatusChange, Episode, FollowUp, AuditLog,
                    CANDIDATE_STATUS, ACTIVE_STATUSES, User, USER_PENDING, REFERRAL_STATUS)
from core import team_required, decider_required, audit, parse_date, num, portal_alerts
from schemas import months_since

main_bp = Blueprint("main", __name__)


def next_monday(d=None):
    d = d or date.today()
    return d + timedelta(days=(7 - d.weekday()) % 7)


@main_bp.route("/")
@login_required
def dashboard():
    if not current_user.is_team:
        refs = Referral.query.filter_by(referring_user_id=current_user.id).order_by(Referral.created_at.desc()).all()
        return render_template("dashboard_referrer.html", referrals=refs)
    today = date.today()
    counts = {s: Candidate.query.filter_by(status=s).count() for s in CANDIDATE_STATUS}
    due_review = Candidate.query.filter(Candidate.status.in_(ACTIVE_STATUSES), Candidate.next_review_due.isnot(None),
                                        Candidate.next_review_due <= today + timedelta(days=14)).order_by(Candidate.next_review_due).all()
    new_refs = Referral.query.filter(Referral.status.in_(["new", "evaluation"])).order_by(Referral.created_at).all()
    open_eps = Episode.query.filter(Episode.stage.notin_(["discharged", "cancelled"])).order_by(Episode.created_at.desc()).all()
    drafts = MDTCase.query.filter_by(status="draft").order_by(MDTCase.mdt_date).all()
    # post-transplant follow-ups due in the next 14 days (or overdue)
    due_fu = FollowUp.query.filter(FollowUp.next_visit_date.isnot(None), FollowUp.next_visit_date <= today + timedelta(days=14)).all()
    latest = {}
    for f in due_fu:
        later = FollowUp.query.filter(FollowUp.patient_id == f.patient_id, FollowUp.visit_date > f.visit_date).first()
        if not later:
            latest[f.patient_id] = f
    pending_users = User.query.filter_by(status=USER_PENDING).count() if current_user.can_manage_users else 0
    return render_template("dashboard.html", counts=counts, due_review=due_review, new_refs=new_refs, open_eps=open_eps, drafts=drafts,
                           due_followups=sorted(latest.values(), key=lambda f: f.next_visit_date), next_mdt=next_monday(), pending_users=pending_users,
                           total_active=sum(counts[s] for s in ACTIVE_STATUSES), transplanted=counts["transplanted"])


@main_bp.route("/candidates")
@team_required
def candidates():
    status = request.args.get("status", "")
    q = Candidate.query.join(Patient)
    if status in CANDIDATE_STATUS:
        q = q.filter(Candidate.status == status)
    elif status != "all":
        q = q.filter(Candidate.status.in_(ACTIVE_STATUSES))
    rows = q.order_by(Candidate.priority.desc(), Candidate.listing_date).all()
    return render_template("candidates.html", rows=rows, status=status or "active")


@main_bp.route("/candidates/<int:cid>/status", methods=["POST"])
@decider_required
def candidate_status(cid):
    c = db.session.get(Candidate, cid) or abort(404)
    new = request.form.get("status")
    if new not in CANDIDATE_STATUS:
        abort(400)
    reason = request.form.get("reason", "").strip()
    if new != c.status:
        db.session.add(CandidateStatusChange(candidate_id=c.id, from_status=c.status, to_status=new, reason=reason, by_user_id=current_user.id))
        c.status = new
        audit("candidate_status", c.patient_id, f"-> {new}: {reason}")
    c.notes = request.form.get("notes", c.notes)
    c.next_review_due = parse_date(request.form.get("next_review_due")) or c.next_review_due
    db.session.commit()
    flash("Candidate updated.", "success")
    return redirect(request.referrer or url_for("main.candidates"))


@main_bp.route("/audit")
@login_required
def audit_log():
    if current_user.role != "admin":
        abort(403)
    rows = AuditLog.query.order_by(AuditLog.at.desc()).limit(300).all()
    return render_template("audit.html", rows=rows)


def _today_data():
    today = date.today()
    nm = next_monday(today)
    rows = dict(
        next_mdt=nm,
        mdt_cases=MDTCase.query.filter(MDTCase.mdt_date == nm).order_by(MDTCase.id).all(),
        mdt_drafts=MDTCase.query.filter_by(status="draft").order_by(MDTCase.mdt_date).all(),
        new_refs=Referral.query.filter(Referral.status.in_(["new", "evaluation"])).order_by(Referral.created_at).all(),
        due_review=Candidate.query.filter(Candidate.status.in_(ACTIVE_STATUSES), Candidate.next_review_due.isnot(None),
                                          Candidate.next_review_due <= today + timedelta(days=14)).order_by(Candidate.next_review_due).all(),
        open_eps=Episode.query.filter(Episode.stage.notin_(["discharged", "cancelled"])).order_by(Episode.created_at.desc()).all(),
        listed=Candidate.query.filter(Candidate.status.in_(("listed", "conditional"))).order_by(Candidate.priority.desc(), Candidate.listing_date).all(),
    )
    due = FollowUp.query.filter(FollowUp.next_visit_date.isnot(None), FollowUp.next_visit_date <= today + timedelta(days=14)).all()
    latest = {}
    for f in due:
        if not FollowUp.query.filter(FollowUp.patient_id == f.patient_id, FollowUp.visit_date > f.visit_date).first():
            latest[f.patient_id] = f
    rows["due_followups"] = sorted(latest.values(), key=lambda f: f.next_visit_date)
    return rows


@main_bp.route("/today")
@team_required
def today():
    return render_template("today.html", **_today_data())


@main_bp.route("/today/print")
@team_required
def today_print():
    audit("today_board_printed")
    db.session.commit()
    return render_template("print_today.html", **_today_data())


@main_bp.route("/api/main/patient-status")
def patient_status_api():
    """For the main app's cross-portal warning: is this Civil ID active in the Transplant unit? Key-protected."""
    key = current_app.config.get("PORTAL_SSO_SECRET", "")
    if not key:
        abort(404)
    if not hmac.compare_digest(request.headers.get("X-Portal-Key", "").encode(), key.encode()):
        abort(403)
    cid = (request.args.get("civil_id") or "").strip()
    p = Patient.query.filter_by(civil_id=cid).first() if cid else None
    items = []
    if p:
        c = Candidate.query.filter_by(patient_id=p.id).first()
        if c and c.status in ACTIVE_STATUSES:
            items.append({"label": "Lung transplant candidate", "status": CANDIDATE_STATUS[c.status], "detail": c.diagnosis or ""})
        for e in Episode.query.filter_by(patient_id=p.id).all():
            if e.stage not in ("discharged", "cancelled"):
                items.append({"label": "Transplant episode", "status": e.stage, "detail": ""})
        for r in Referral.query.filter_by(patient_id=p.id).all():
            if r.status in ("new", "evaluation"):
                items.append({"label": "Transplant referral", "status": REFERRAL_STATUS.get(r.status, r.status), "detail": r.primary_diagnosis or ""})
    try:
        db.session.add(AuditLog(user_id=None, action="portal_status_lookup", detail=f"civil {cid[:4]}*** items={len(items)}"))
        db.session.commit()
    except Exception:
        db.session.rollback()
    return jsonify({"found": bool(p), "items": items})
