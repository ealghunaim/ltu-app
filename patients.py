import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort, jsonify, current_app
from flask_login import current_user

from models import (db, Patient, Referral, MDTCase, Candidate, Episode, FollowUp, TroughLevel, REFERRAL_STATUS)
from core import team_required, audit, next_case_no, parse_date, ensure_candidate
from schemas import months_since, tac_target, fev1_drop_pct
from charts import line_chart

patients_bp = Blueprint("patients", __name__, url_prefix="/patients")


def lookup_main_app(civil_id):
    """Ask the main Thoracic app for demographics by Civil ID (read-only, key-protected)."""
    base, key = current_app.config["MAIN_APP_URL"], current_app.config["MAIN_APP_LTU_KEY"]
    if not (base and key):
        return {"found": False, "configured": False}
    try:
        r = requests.get(base + "/api/ltu/patient-lookup", params={"civil_id": civil_id}, headers={"X-LTU-Key": key}, timeout=6)
        if r.status_code == 200:
            d = r.json()
            d["configured"] = True
            return d
        return {"found": False, "configured": True, "error": r.status_code}
    except requests.RequestException as e:
        return {"found": False, "configured": True, "error": str(e)[:80]}


@patients_bp.route("")
@team_required
def search():
    q = request.args.get("q", "").strip()
    rows = []
    if q:
        like = f"%{q}%"
        rows = Patient.query.filter(db.or_(Patient.full_name.ilike(like), Patient.civil_id.like(like), Patient.ltu_case_no.ilike(like),
                                           Patient.file_number.ilike(like))).order_by(Patient.full_name).limit(50).all()
    else:
        rows = Patient.query.order_by(Patient.created_at.desc()).limit(30).all()
    return render_template("patients.html", rows=rows, q=q)


@patients_bp.route("/lookup")
def lookup():
    """JSON: local LTU record first, then main app. Used by the 'find by Civil ID' boxes."""
    from flask_login import login_required
    if not current_user.is_authenticated:
        abort(401)
    cid = request.args.get("civil_id", "").strip()
    if not cid:
        return jsonify({"found": False})
    p = Patient.query.filter_by(civil_id=cid).first()
    if p:
        return jsonify({"found": True, "source": "ltu", "id": p.id, "full_name": p.full_name, "sex": p.sex,
                        "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else "", "nationality": p.nationality or "",
                        "phone": p.phone or "", "blood_group": p.blood_group or "", "file_number": p.file_number or ""})
    if not current_user.is_team:
        return jsonify({"found": False})
    d = lookup_main_app(cid)
    if d.get("found"):
        d["source"] = "main_app"
        audit("main_app_lookup", None, f"civil_id {cid}")
        db.session.commit()
    return jsonify(d)


def _fill(p, f):
    p.full_name = f.get("full_name", p.full_name or "").strip()
    p.sex = f.get("sex") or p.sex
    p.date_of_birth = parse_date(f.get("date_of_birth")) or p.date_of_birth
    p.nationality = f.get("nationality", "").strip() or p.nationality
    p.phone = f.get("phone", "").strip() or p.phone
    p.blood_group = f.get("blood_group", "").strip() or p.blood_group
    p.file_number = f.get("file_number", "").strip() or p.file_number


def get_or_create_patient(f):
    """Find by Civil ID or create from a form dict; returns (patient, created)."""
    cid = (f.get("civil_id") or "").strip()
    if not cid or not (f.get("full_name") or "").strip():
        return None, False
    p = Patient.query.filter_by(civil_id=cid).first()
    if p:
        return p, False
    p = Patient(civil_id=cid, ltu_case_no=next_case_no(), source=f.get("source") or "manual")
    _fill(p, f)
    db.session.add(p)
    db.session.flush()
    return p, True


@patients_bp.route("/new", methods=["GET", "POST"])
@team_required
def new():
    if request.method == "POST":
        p, created = get_or_create_patient(request.form)
        if not p:
            flash("Civil ID and full name are required.", "error")
        else:
            audit("patient_created" if created else "patient_opened", p.id)
            db.session.commit()
            flash("Patient registered." if created else "That Civil ID is already registered - opened the existing record.", "success")
            return redirect(url_for("patients.detail", pid=p.id))
    return render_template("patient_new.html", lookup_on=bool(current_app.config["MAIN_APP_URL"] and current_app.config["MAIN_APP_LTU_KEY"]))


@patients_bp.route("/<int:pid>")
@team_required
def detail(pid):
    p = db.session.get(Patient, pid) or abort(404)
    audit("patient_viewed", p.id)
    db.session.commit()
    tx = next((e for e in sorted(p.episodes, key=lambda e: e.transplant_date or e.created_at.date()) if e.transplant_date), None)
    fus = sorted(p.followups, key=lambda f: f.visit_date)
    fev_pts = [(f.visit_date.strftime("%d/%m/%y"), f.fev1_l) for f in fus]
    troughs = TroughLevel.query.filter_by(patient_id=p.id).order_by(TroughLevel.drawn_at).all()
    tr_pts = [(t.drawn_at.strftime("%d/%m"), t.value) for t in troughs[-24:]]
    last_months = months_since(tx.transplant_date, troughs[-1].drawn_at.date()) if (tx and troughs) else None
    return render_template(
        "patient_detail.html", p=p, tx=tx, referrals=Referral.query.filter_by(patient_id=p.id).order_by(Referral.created_at.desc()).all(),
        mdts=MDTCase.query.filter_by(patient_id=p.id).order_by(MDTCase.mdt_date.desc()).all(), episodes=sorted(p.episodes, key=lambda e: e.created_at, reverse=True),
        followups=list(reversed(fus)), cand=p.candidate, troughs=list(reversed(troughs[-15:])),
        fev_chart=line_chart(fev_pts, unit=" L", title="FEV1 (L)"), tac_chart=line_chart(tr_pts, band=tac_target(last_months), unit=" ng/mL", title="Tacrolimus trough", color="#7a3e9d"),
        fev_drop=fev1_drop_pct(max([f.fev1_l for f in fus if f.fev1_l] or [0]) or None, fus[-1].fev1_l if fus and fus[-1].fev1_l else None),
        months_post=months_since(tx.transplant_date, __import__("datetime").date.today()) if tx else None,
        REFERRAL_STATUS=REFERRAL_STATUS)


@patients_bp.route("/<int:pid>/edit", methods=["POST"])
@team_required
def edit(pid):
    p = db.session.get(Patient, pid) or abort(404)
    _fill(p, request.form)
    audit("patient_edited", p.id)
    db.session.commit()
    flash("Demographics updated.", "success")
    return redirect(url_for("patients.detail", pid=p.id))
