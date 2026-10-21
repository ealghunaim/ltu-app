"""Print views (A4, hospital header, patient banner, audit-logged)."""
from datetime import date, datetime, timedelta

from flask import Blueprint, render_template, request, abort
from flask_login import login_required, current_user

from models import (db, Patient, Referral, MDTCase, Candidate, Episode, FollowUp, TroughLevel, CANDIDATE_STATUS, ACTIVE_STATUSES,
                    DECISIONS, CASE_TYPES, REFERRAL_STATUS)
from core import team_required, audit, parse_date
from schemas import (REFERRAL_CLINICAL, FOLLOWUP_FORM, VISIT_TYPES, DISCHARGE_GATE, tac_target, months_since, fev1_drop_pct)
from charts import line_chart
from episodes import SECTION_SETS, STAGES, PROCEDURES
from followups import due_visits, _tx_episode
from views import next_monday

prints_bp = Blueprint("prints", __name__, url_prefix="/print")

EPISODE_TAB_TITLES = [("offer", "Organ offer"), ("preop", "Pre-operative"), ("intraop", "Intra-operative"), ("icu", "CTICU"), ("discharge", "Discharge")]


def kuwait_now():
    return datetime.utcnow() + timedelta(hours=3)


def pv(field, value):
    """Format one stored form value for print ('' when empty)."""
    t = field.get("type")
    if value is None or value == "" or value == [] or value is False:
        return ""
    if value is True:
        return "Yes"
    opts = dict(field.get("options") or [])
    if t == "multi":
        return ", ".join(opts.get(v, v) for v in value)
    if t == "select":
        return opts.get(value, value)
    if t == "yesno":
        return {"yes": "Yes", "no": "No"}.get(value, value)
    if t == "datetime" and isinstance(value, str):
        return value.replace("T", " ")
    return str(value)


@prints_bp.app_context_processor
def _print_ctx():
    return dict(pv=pv, printed_at=kuwait_now())


def _banner_audit(action, patient_id, detail=""):
    audit(action, patient_id, detail)
    db.session.commit()


@prints_bp.route("/patient/<int:pid>")
@team_required
def patient(pid):
    p = db.session.get(Patient, pid) or abort(404)
    fus = sorted(p.followups, key=lambda f: f.visit_date)
    troughs = TroughLevel.query.filter_by(patient_id=p.id).order_by(TroughLevel.drawn_at).all()
    tx = next((e for e in sorted(p.episodes, key=lambda e: e.transplant_date or e.created_at.date()) if e.transplant_date), None)
    months = months_since(tx.transplant_date, date.today()) if tx else None
    _banner_audit("patient_printed", p.id)
    return render_template(
        "print_patient.html", p=p, cand=p.candidate, tx=tx, months=months,
        referrals=Referral.query.filter_by(patient_id=p.id).order_by(Referral.created_at.desc()).all(),
        mdts=MDTCase.query.filter_by(patient_id=p.id).order_by(MDTCase.mdt_date.desc()).all(),
        episodes=sorted(p.episodes, key=lambda e: e.created_at, reverse=True), followups=list(reversed(fus)),
        fev_chart=line_chart([(f.visit_date.strftime("%d/%m/%y"), f.fev1_l) for f in fus], unit=" L", title="FEV1 (L)"),
        tac_chart=line_chart([(t.drawn_at.strftime("%d/%m/%y"), t.value) for t in troughs[-20:]], band=tac_target(months or 0), unit=" ng/mL",
                             title="Tacrolimus trough", color="#7a3e9d"),
        VISIT_TYPES=dict(VISIT_TYPES), PROCEDURES=PROCEDURES)


@prints_bp.route("/referral/<int:rid>")
@login_required
def referral(rid):
    r = db.session.get(Referral, rid) or abort(404)
    if not (current_user.is_team or r.referring_user_id == current_user.id):
        abort(403)
    mdt = MDTCase.query.filter_by(referral_id=r.id, status="final").order_by(MDTCase.finalised_at.desc()).first()
    if mdt and not current_user.is_team and not r.decision_sent_at:
        mdt = None
    _banner_audit("referral_printed", r.patient_id, f"referral {r.id}")
    return render_template("print_referral.html", r=r, p=r.patient, mdt=mdt, sections=REFERRAL_CLINICAL, data=r.get_data("clinical"))


@prints_bp.route("/episode/<int:eid>")
@team_required
def episode(eid):
    e = db.session.get(Episode, eid) or abort(404)
    blocks = []
    for tab, title in EPISODE_TAB_TITLES:
        secs = [(key, stitle, fields, e.get_data(key)) for key, stitle, fields in SECTION_SETS[tab]]
        blocks.append((title, secs))
    gate = e.get_data("discharge_gate")
    troughs = TroughLevel.query.filter_by(episode_id=e.id).order_by(TroughLevel.drawn_at).all()
    months = months_since(e.transplant_date, date.today()) if e.transplant_date else 0
    _banner_audit("episode_printed", e.patient_id, f"episode {e.id}")
    return render_template("print_episode.html", e=e, p=e.patient, blocks=blocks, troughs=troughs, stages=dict(STAGES), procedures=PROCEDURES,
                           target=tac_target(months or 0), gate_done=sum(1 for k, _ in DISCHARGE_GATE if gate.get(k)), gate_total=len(DISCHARGE_GATE))


@prints_bp.route("/followup/<int:fid>")
@team_required
def followup(fid):
    fu = db.session.get(FollowUp, fid) or abort(404)
    ep = fu.episode or _tx_episode(fu.patient_id)
    months = months_since(ep.transplant_date, fu.visit_date) if ep else None
    tgt = tac_target(months) if months is not None else None
    sections = [(k, t, f, fu.get_data(k)) for k, t, f in FOLLOWUP_FORM]
    _banner_audit("followup_printed", fu.patient_id, f"followup {fu.id}")
    return render_template("print_followup.html", fu=fu, p=fu.patient, ep=ep, months=months, tgt=tgt, sections=sections, VISIT_TYPES=dict(VISIT_TYPES))


@prints_bp.route("/waitlist")
@team_required
def waitlist():
    status = request.args.get("status", "active")
    q = Candidate.query.join(Patient)
    if status in CANDIDATE_STATUS:
        q = q.filter(Candidate.status == status)
    elif status != "all":
        status = "active"
        q = q.filter(Candidate.status.in_(ACTIVE_STATUSES))
    rows = q.order_by(Candidate.status, Patient.full_name).all()
    _banner_audit("waitlist_printed", None, status)
    return render_template("print_waitlist.html", rows=rows, status=status)


@prints_bp.route("/followups")
@team_required
def followup_schedule():
    today = date.today()
    rows = []
    for p in Patient.query.join(Episode).filter(Episode.transplant_date.isnot(None)).distinct().all():
        nxt = next((d for d in due_visits(p, today) if not d["done"]), None)
        last = max(p.followups, key=lambda f: f.visit_date) if p.followups else None
        rows.append({"p": p, "next": nxt, "last": last, "months": months_since(_tx_episode(p.id).transplant_date, today)})
    rows.sort(key=lambda r: (r["next"]["due"] if r["next"] else date(2999, 1, 1)))
    _banner_audit("followup_schedule_printed", None)
    return render_template("print_followup_schedule.html", rows=rows, today=today)


@prints_bp.route("/mdt-agenda")
@team_required
def mdt_agenda():
    d = parse_date(request.args.get("date")) or next_monday()
    cases = MDTCase.query.filter_by(mdt_date=d).order_by(MDTCase.id).all()
    _banner_audit("mdt_agenda_printed", None, d.isoformat())
    return render_template("print_mdt_agenda.html", d=d, cases=cases, case_types=CASE_TYPES, decisions=DECISIONS)
