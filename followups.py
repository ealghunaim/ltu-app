from datetime import date, timedelta

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user

from models import db, FollowUp, Patient, Episode, TroughLevel
from core import team_required, audit, parse_date, num
from schemas import (FOLLOWUP_FORM, VISIT_TYPES, parse_section, months_since, tac_target, fev1_drop_pct)

followups_bp = Blueprint("followups", __name__)
SCHEDULE = [("month1", 1), ("month3", 3), ("month6", 6), ("month9", 9), ("month12", 12)]


def _tx_episode(patient_id):
    return (Episode.query.filter(Episode.patient_id == patient_id, Episode.transplant_date.isnot(None))
            .order_by(Episode.transplant_date.desc()).first())


def due_visits(patient, today=None):
    """Protocol Year-1 schedule (months 1/3/6/9/12 after the transplant date) minus visits already recorded."""
    today = today or date.today()
    ep = _tx_episode(patient.id)
    if not ep:
        return []
    done = {f.visit_type for f in patient.followups}
    out = []
    for key, m in SCHEDULE:
        yr, mo = ep.transplant_date.year + (ep.transplant_date.month - 1 + m) // 12, (ep.transplant_date.month - 1 + m) % 12 + 1
        try:
            due = date(yr, mo, min(ep.transplant_date.day, 28))
        except ValueError:
            continue
        out.append({"type": key, "label": dict(VISIT_TYPES)[key], "due": due, "done": key in done, "overdue": key not in done and due < today})
    return out


@followups_bp.route("/followups")
@team_required
def listing():
    today = date.today()
    rows = []
    for p in Patient.query.join(Episode).filter(Episode.transplant_date.isnot(None)).distinct().all():
        nxt = next((d for d in due_visits(p, today) if not d["done"]), None)
        last = max(p.followups, key=lambda f: f.visit_date) if p.followups else None
        rows.append({"p": p, "next": nxt, "last": last, "months": months_since(_tx_episode(p.id).transplant_date, today)})
    rows.sort(key=lambda r: (r["next"]["due"] if r["next"] else date(2999, 1, 1)))
    return render_template("followups.html", rows=rows, today=today)


@followups_bp.route("/patients/<int:pid>/followups/new", methods=["GET", "POST"])
@team_required
def new(pid):
    p = db.session.get(Patient, pid) or abort(404)
    ep = _tx_episode(p.id)
    vtype = request.values.get("type") if request.values.get("type") in dict(VISIT_TYPES) else "unscheduled"
    if request.method == "POST":
        f = request.form
        fu = FollowUp(patient_id=p.id, episode_id=ep.id if ep else None, created_by_id=current_user.id, visit_type=vtype,
                      visit_date=parse_date(f.get("visit_date")) or date.today())
        _apply(fu, f)
        db.session.add(fu)
        audit("followup_created", p.id, f"{vtype}")
        db.session.commit()
        _warnings(fu, p, ep)
        return redirect(url_for("followups.view", fid=fu.id))
    return render_template("followup_form.html", p=p, fu=None, state={}, sections=FOLLOWUP_FORM, vtype=vtype, visit_types=VISIT_TYPES, ep=ep,
                           months=months_since(ep.transplant_date, date.today()) if ep else None)


def _apply(fu, f):
    fu.fev1_l, fu.fev1_pct, fu.fvc_l = num(f.get("fev1_l")), num(f.get("fev1_pct")), num(f.get("fvc_l"))
    fu.tacrolimus, fu.creatinine = num(f.get("tacrolimus")), num(f.get("creatinine"))
    fu.next_visit_date = parse_date(f.get("next_visit_date"))
    for key, _t, fields in FOLLOWUP_FORM:
        fu.set_section(key, parse_section(fields, f, key + "__"))
    if fu.tacrolimus is not None:
        db.session.add(TroughLevel(patient_id=fu.patient_id, episode_id=fu.episode_id, value=fu.tacrolimus, drawn_at=__import__("datetime").datetime.combine(fu.visit_date, __import__("datetime").time(6, 0))))


def _warnings(fu, p, ep):
    msgs = []
    if ep and fu.tacrolimus is not None:
        tgt = tac_target(months_since(ep.transplant_date, fu.visit_date))
        if tgt and not (tgt[0] <= fu.tacrolimus <= tgt[1]):
            msgs.append(f"Tacrolimus trough {fu.tacrolimus:g} ng/mL is outside the target {tgt[0]:g}-{tgt[1]:g}.")
    v = fu.get_data("vitals")
    drop = fev1_drop_pct(num(v.get("home_spiro_baseline")), num(v.get("home_spiro_latest")))
    if drop is not None and drop > 10:
        msgs.append(f"Home spirometry FEV1 is {drop:g}% below personal best (>10% - warning sign: evaluate for rejection/infection).")
    prior = [x.fev1_l for x in p.followups if x.id != fu.id and x.fev1_l]
    if fu.fev1_l and prior and fev1_drop_pct(max(prior), fu.fev1_l) and fev1_drop_pct(max(prior), fu.fev1_l) >= 20:
        msgs.append("Clinic FEV1 is >=20% below the best previous value - assess for CLAD.")
    for m in msgs:
        flash(m, "warning")


@followups_bp.route("/followups/<int:fid>", methods=["GET", "POST"])
@team_required
def view(fid):
    fu = db.session.get(FollowUp, fid) or abort(404)
    p = fu.patient
    ep = fu.episode or _tx_episode(p.id)
    if request.method == "POST":
        fu.visit_date = parse_date(request.form.get("visit_date")) or fu.visit_date
        old_tac = fu.tacrolimus
        _apply(fu, request.form)
        audit("followup_edited", p.id, f"followup {fu.id}")
        db.session.commit()
        flash("Visit updated.", "success")
        return redirect(url_for("followups.view", fid=fu.id))
    state = {k: fu.get_data(k) for k, _t, _f in FOLLOWUP_FORM}
    audit("followup_viewed", p.id, f"followup {fu.id}")
    db.session.commit()
    return render_template("followup_form.html", p=p, fu=fu, state=state, sections=FOLLOWUP_FORM, vtype=fu.visit_type, visit_types=VISIT_TYPES, ep=ep,
                           months=months_since(ep.transplant_date, fu.visit_date) if ep else None)
