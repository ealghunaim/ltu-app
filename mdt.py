from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user

from models import (db, MDTCase, Patient, Referral, Candidate, CandidateStatusChange, CASE_TYPES, DECISIONS)
from core import team_required, decider_required, audit, parse_date, num, ensure_candidate
from schemas import MDT_FORM, NEXT_REVIEW, parse_section, F

mdt_bp = Blueprint("mdt", __name__, url_prefix="/mdt")

_DECISION_TO_STATUS = {"list": "listed", "conditional": "conditional", "defer": "evaluation", "inactive": "inactive", "decline": "declined"}


def next_review_date(code, on, specific):
    if code == "1w":
        return on + timedelta(days=7)
    if code == "1m":
        return on + timedelta(days=30)
    if code == "3m":
        return on + timedelta(days=91)
    if code == "6m":
        return on + timedelta(days=182)
    return specific


@mdt_bp.route("")
@team_required
def listing():
    st = request.args.get("status")
    q = MDTCase.query
    if st in ("draft", "final"):
        q = q.filter_by(status=st)
    return render_template("mdt_list.html", rows=q.order_by(MDTCase.mdt_date.desc(), MDTCase.id.desc()).limit(200).all(), st=st)


@mdt_bp.route("/new")
@team_required
def new():
    pid = request.args.get("patient_id", type=int)
    p = db.session.get(Patient, pid or 0) or abort(404)
    rid = request.args.get("referral_id", type=int)
    ref = db.session.get(Referral, rid) if rid else None
    case_type = request.args.get("case_type") if request.args.get("case_type") in CASE_TYPES else ("new_referral" if ref else "waitlist_review")
    m = MDTCase(patient_id=p.id, referral_id=ref.id if ref else None, case_type=case_type, created_by_id=current_user.id)
    if ref:
        c = ref.get_data("clinical")
        summary = {k: c.get(k, "") for k in ("aetiology", "disease_duration", "fev1_pct", "fvc_pct", "dlco_pct", "tlc_pct", "sixmwt_m", "spo2_rest", "spo2_exertion", "o2_requirement", "mpap")}
        summary["primary_diagnosis"] = ref.primary_diagnosis
        summary["nyha"] = c.get("mmrc", "")
        m.set_section("summary", summary)
        if ref.status == "new":
            ref.status = "presented"
    db.session.add(m)
    audit("mdt_created", p.id)
    db.session.commit()
    return redirect(url_for("mdt.edit", mid=m.id))


def _form_state(m):
    return {key: m.get_data(key) for key, _t, _f in MDT_FORM}


@mdt_bp.route("/<int:mid>", methods=["GET", "POST"])
@team_required
def edit(mid):
    m = db.session.get(MDTCase, mid) or abort(404)
    final = m.status == "final"
    if request.method == "POST":
        if final:
            flash("This MDT form is final and cannot be edited.", "error")
            return redirect(url_for("mdt.edit", mid=m.id))
        f = request.form
        m.mdt_date = parse_date(f.get("mdt_date")) or m.mdt_date
        m.case_type = f.get("case_type") if f.get("case_type") in CASE_TYPES else m.case_type
        for key, _t, fields in MDT_FORM:
            m.set_section(key, parse_section(fields, f, key + "__"))
        m.set_section("review", {"next_review": f.get("next_review", ""), "next_review_date": f.get("next_review_date", ""), "chair": f.get("chair_name", "")})
        m.decision = f.get("decision") if f.get("decision") in DECISIONS else None
        m.chair_name = f.get("chair_name", "").strip()
        m.next_review_date = next_review_date(f.get("next_review"), m.mdt_date or date.today(), parse_date(f.get("next_review_date")))
        audit("mdt_saved", m.patient_id, f"mdt {m.id}")
        db.session.commit()
        if f.get("finalise"):
            return finalise(m.id)
        flash("Draft saved.", "success")
        return redirect(url_for("mdt.edit", mid=m.id))
    return render_template("mdt_form.html", m=m, sections=MDT_FORM, state=_form_state(m), review=m.get_data("review"), next_review=NEXT_REVIEW,
                           final=final, case_types=CASE_TYPES, decisions=DECISIONS)


@mdt_bp.route("/<int:mid>/finalise", methods=["POST"])
@decider_required
def finalise(mid):
    m = db.session.get(MDTCase, mid) or abort(404)
    if m.status == "final":
        return redirect(url_for("mdt.edit", mid=m.id))
    if not m.decision:
        flash("Choose an MDT decision (section G) before finalising.", "error")
        return redirect(url_for("mdt.edit", mid=m.id))
    if not m.chair_name:
        flash("Enter the MDT chair name before finalising.", "error")
        return redirect(url_for("mdt.edit", mid=m.id))
    listing = m.get_data("listing")
    c = ensure_candidate(m.patient)
    new_status = _DECISION_TO_STATUS[m.decision]
    if m.decision == "decline" and c.status in ("listed", "inactive", "conditional"):
        new_status = "delisted"
    if c.status != new_status:
        db.session.add(CandidateStatusChange(candidate_id=c.id, from_status=c.status, to_status=new_status, by_user_id=current_user.id, mdt_case_id=m.id,
                                             reason=(listing.get("rationale") or "MDT decision: " + m.decision)))
    c.status = new_status
    c.diagnosis = m.get_data("summary").get("primary_diagnosis") or c.diagnosis
    if m.decision == "list" and not c.listing_date:
        c.listing_date = m.mdt_date
    if m.decision in ("list", "conditional"):
        c.procedure_type = listing.get("procedure_type") or c.procedure_type
        c.side = listing.get("side") or c.side
        c.priority = listing.get("priority") or c.priority
        c.tlc_low, c.tlc_high = num(listing.get("tlc_low")), num(listing.get("tlc_high"))
        c.special_donor_notes = listing.get("special_donor") or c.special_donor_notes
    c.last_review_date = m.mdt_date
    c.next_review_due = m.next_review_date
    m.status = "final"
    m.finalised_by_id = current_user.id
    m.finalised_at = datetime.utcnow()
    if m.referral and m.referral.status != "decided":
        m.referral.status = "decided"
    audit("mdt_finalised", m.patient_id, f"mdt {m.id}: {m.decision}")
    db.session.commit()
    flash("MDT decision finalised and the candidate registry updated. Send the written decision to the referring physician within 5 working days.", "success")
    return redirect(url_for("mdt.edit", mid=m.id))


@mdt_bp.route("/<int:mid>/reopen", methods=["POST"])
@decider_required
def reopen(mid):
    m = db.session.get(MDTCase, mid) or abort(404)
    m.status = "draft"
    audit("mdt_reopened", m.patient_id, f"mdt {m.id}")
    db.session.commit()
    return redirect(url_for("mdt.edit", mid=m.id))


@mdt_bp.route("/<int:mid>/print")
@team_required
def print_form(mid):
    m = db.session.get(MDTCase, mid) or abort(404)
    audit("mdt_printed", m.patient_id, f"mdt {m.id}")
    db.session.commit()
    return render_template("mdt_print.html", m=m, sections=MDT_FORM, state=_form_state(m), review=m.get_data("review"), decisions=DECISIONS, case_types=CASE_TYPES)
