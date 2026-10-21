from datetime import date, datetime

from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import current_user

from models import (db, Episode, Patient, Candidate, CandidateStatusChange, PGDAssessment, TroughLevel)
from core import team_required, audit, parse_date, parse_dt, num, ensure_candidate
from schemas import (EPISODE_OFFER, EPISODE_PREOP, EPISODE_INTRAOP, EPISODE_ICU, EPISODE_DISCHARGE, parse_section, completion, cmv_advice,
                     pgd_grade, PGD_MANAGEMENT, tac_target, months_since, BRONCH_SCHEDULE, DISCHARGE_GATE)

episodes_bp = Blueprint("episodes", __name__, url_prefix="/episodes")

SECTION_SETS = {"offer": EPISODE_OFFER, "preop": EPISODE_PREOP, "intraop": EPISODE_INTRAOP, "icu": EPISODE_ICU, "discharge": EPISODE_DISCHARGE}
STAGES = [("offer", "Organ offer"), ("admitted", "Admitted / pre-op"), ("or", "Operating room"), ("icu", "CTICU"), ("ward", "Step-down ward"), ("discharged", "Discharged")]
STAGE_KEYS = [k for k, _ in STAGES]
PROCEDURES = {"right_slt": "Right single lung", "left_slt": "Left single lung", "bslt": "Bilateral sequential lung"}


@episodes_bp.route("")
@team_required
def listing():
    rows = Episode.query.order_by(Episode.created_at.desc()).all()
    return render_template("episodes.html", rows=rows, stages=dict(STAGES), procedures=PROCEDURES)


@episodes_bp.route("/new", methods=["POST"])
@team_required
def new():
    p = db.session.get(Patient, request.form.get("patient_id", type=int) or 0) or abort(404)
    open_ep = Episode.query.filter(Episode.patient_id == p.id, Episode.stage.notin_(["discharged", "cancelled"])).first()
    if open_ep:
        flash("This patient already has an open transplant episode.", "warning")
        return redirect(url_for("episodes.view", eid=open_ep.id))
    e = Episode(patient_id=p.id, stage="offer", offer_at=datetime.utcnow(), offer_decision="pending", created_by_id=current_user.id)
    db.session.add(e)
    audit("episode_created", p.id)
    db.session.commit()
    return redirect(url_for("episodes.view", eid=e.id))


@episodes_bp.route("/<int:eid>")
@team_required
def view(eid):
    e = db.session.get(Episode, eid) or abort(404)
    audit("episode_viewed", e.patient_id, f"episode {e.id}")
    db.session.commit()
    sets = {}
    for tab, secs in SECTION_SETS.items():
        sets[tab] = [(key, title, fields, e.get_data(key), completion(fields, e.get_data(key))) for key, title, fields in secs]
    troughs = TroughLevel.query.filter_by(episode_id=e.id).order_by(TroughLevel.drawn_at.desc()).limit(30).all()
    months = months_since(e.transplant_date, date.today()) if e.transplant_date else 0
    target = tac_target(months if months is not None else 0) or tac_target(0)
    worst = max([a.grade for a in e.pgd if a.grade is not None] or [None]) if e.pgd else None
    gate = e.get_data("discharge_gate")
    gate_done = sum(1 for k, _ in DISCHARGE_GATE if gate.get(k))
    return render_template("episode.html", e=e, sets=sets, stages=STAGES, stage_idx=STAGE_KEYS.index(e.stage) if e.stage in STAGE_KEYS else 0,
                           procedures=PROCEDURES, troughs=troughs, target=target, worst_pgd=worst, pgd_text=PGD_MANAGEMENT, gate_done=gate_done,
                           gate_total=len(DISCHARGE_GATE), cmv=cmv_advice(e.donor_cmv, e.recipient_cmv), bronch=BRONCH_SCHEDULE)


@episodes_bp.route("/<int:eid>/section/<tab>/<key>", methods=["POST"])
@team_required
def save_section(eid, tab, key):
    e = db.session.get(Episode, eid) or abort(404)
    fields = next((f for k, _t, f in SECTION_SETS.get(tab, []) if k == key), None)
    if fields is None:
        abort(404)
    vals = parse_section(fields, request.form, key + "__")
    e.set_section(key, vals)
    if key == "offer":
        e.offer_at = parse_dt(vals.get("kts_notified_at")) or e.offer_at
    if key == "preop":
        e.recipient_cmv = vals.get("recipient_cmv") or e.recipient_cmv
    audit("episode_section", e.patient_id, f"episode {e.id} {key}")
    db.session.commit()
    flash("Saved.", "success")
    return redirect(url_for("episodes.view", eid=e.id, _anchor=tab))


@episodes_bp.route("/<int:eid>/core", methods=["POST"])
@team_required
def save_core(eid):
    e = db.session.get(Episode, eid) or abort(404)
    f = request.form
    e.procedure = f.get("procedure") if f.get("procedure") in PROCEDURES else e.procedure
    e.offer_decision = f.get("offer_decision") if f.get("offer_decision") in ("pending", "accepted", "declined") else e.offer_decision
    e.donor_cmv = f.get("donor_cmv") or e.donor_cmv
    e.recipient_cmv = f.get("recipient_cmv") or e.recipient_cmv
    e.cross_clamp_at = parse_dt(f.get("cross_clamp_at")) or e.cross_clamp_at
    e.reperfusion_at = parse_dt(f.get("reperfusion_at")) or e.reperfusion_at
    e.transplant_date = parse_date(f.get("transplant_date")) or e.transplant_date
    chk = e.cold_ischaemic_hours
    if chk is not None:
        limit = 6 if e.procedure == "bslt" else 8
        if chk > limit:
            flash(f"Cold ischaemic time {chk} h exceeds the target ({'<=6 h bilateral' if limit == 6 else '<=8 h single lung'}).", "warning")
    audit("episode_core", e.patient_id, f"episode {e.id}")
    db.session.commit()
    return redirect(url_for("episodes.view", eid=e.id))


@episodes_bp.route("/<int:eid>/stage", methods=["POST"])
@team_required
def stage(eid):
    e = db.session.get(Episode, eid) or abort(404)
    to = request.form.get("stage")
    if to == "cancelled":
        e.stage = "cancelled"
        db.session.commit()
        return redirect(url_for("episodes.view", eid=e.id))
    if to not in STAGE_KEYS:
        abort(400)
    if to == "admitted" and e.offer_decision != "accepted":
        flash("Record the offer as ACCEPTED before admitting the recipient.", "error")
        return redirect(url_for("episodes.view", eid=e.id))
    if to == "discharged":
        gate = e.get_data("discharge_gate")
        missing = [l for k, l in DISCHARGE_GATE if not gate.get(k)]
        if missing:
            flash(f"Discharge gate not met - {len(missing)} criteria outstanding (first: {missing[0]}).", "error")
            return redirect(url_for("episodes.view", eid=e.id, _anchor="discharge"))
        e.discharge_date = date.today()
    if to in ("or", "icu", "ward", "discharged") and not e.transplant_date:
        e.transplant_date = date.today()
    e.stage = to
    if e.transplant_date:
        c = ensure_candidate(e.patient)
        if c.status != "transplanted":
            db.session.add(CandidateStatusChange(candidate_id=c.id, from_status=c.status, to_status="transplanted",
                                                 reason=f"Transplant episode {e.id}", by_user_id=current_user.id))
            c.status = "transplanted"
    audit("episode_stage", e.patient_id, f"episode {e.id} -> {to}")
    db.session.commit()
    return redirect(url_for("episodes.view", eid=e.id))


@episodes_bp.route("/<int:eid>/pgd", methods=["POST"])
@team_required
def add_pgd(eid):
    e = db.session.get(Episode, eid) or abort(404)
    f = request.form
    hours = f.get("hours", type=int)
    if hours not in (0, 24, 48, 72):
        abort(400)
    pao2, fio2 = num(f.get("pao2")), num(f.get("fio2"))
    if fio2 and fio2 > 1.5:
        fio2 = fio2 / 100.0  # entered as %
    a = PGDAssessment.query.filter_by(episode_id=e.id, hours=hours).first() or PGDAssessment(episode_id=e.id, hours=hours)
    a.pao2, a.fio2 = pao2, fio2
    a.infiltrates = f.get("infiltrates") == "on"
    a.on_ecmo = f.get("on_ecmo") == "on"
    a.grade = pgd_grade((pao2 / fio2) if (pao2 and fio2) else None, a.infiltrates, a.on_ecmo)
    db.session.add(a)
    audit("pgd_recorded", e.patient_id, f"episode {e.id} T{hours} grade {a.grade}")
    db.session.commit()
    return redirect(url_for("episodes.view", eid=e.id, _anchor="pgd"))


@episodes_bp.route("/<int:eid>/trough", methods=["POST"])
@team_required
def add_trough(eid):
    e = db.session.get(Episode, eid) or abort(404)
    v = num(request.form.get("value"))
    if v is None:
        flash("Enter the trough value.", "error")
    else:
        db.session.add(TroughLevel(patient_id=e.patient_id, episode_id=e.id, value=v, drug=request.form.get("drug", "tacrolimus"),
                                   drawn_at=parse_dt(request.form.get("drawn_at")) or datetime.utcnow(), by_user_id=current_user.id))
        tgt = tac_target(months_since(e.transplant_date, date.today()) if e.transplant_date else 0)
        if tgt and not (tgt[0] <= v <= tgt[1]) and request.form.get("drug", "tacrolimus") == "tacrolimus":
            flash(f"Tacrolimus trough {v:g} ng/mL is outside the target {tgt[0]:g}-{tgt[1]:g}.", "warning")
        db.session.commit()
    return redirect(url_for("episodes.view", eid=e.id, _anchor="troughs"))
