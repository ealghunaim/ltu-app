import re
from datetime import date, datetime
from functools import wraps

from flask import abort, flash, redirect, url_for, request
from flask_login import current_user, login_required

from models import db, AuditLog, Patient, Candidate


def team_required(view):
    """LTU staff only (everything except the referring-physician role)."""
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if not current_user.is_team:
            abort(403)
        return view(*a, **kw)
    return wrapped


def decider_required(view):
    @wraps(view)
    @login_required
    def wrapped(*a, **kw):
        if not current_user.can_decide:
            flash("Only the Medical Director, Surgical Director or an administrator can do that.", "error")
            return redirect(request.referrer or url_for("main.dashboard"))
        return view(*a, **kw)
    return wrapped


def audit(action, patient_id=None, detail=""):
    db.session.add(AuditLog(user_id=current_user.id if current_user.is_authenticated else None,
                            patient_id=patient_id, action=action, detail=detail[:500]))


def next_case_no():
    year = date.today().year
    n = Patient.query.filter(Patient.ltu_case_no.like(f"LTU-{year}-%")).count() + 1
    while Patient.query.filter_by(ltu_case_no=f"LTU-{year}-{n:03d}").first():
        n += 1
    return f"LTU-{year}-{n:03d}"


def parse_date(s):
    try:
        return date.fromisoformat((s or "").strip())
    except ValueError:
        return None


def parse_dt(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def num(s):
    try:
        return float(str(s).strip())
    except (ValueError, TypeError):
        return None


def safe_next(nxt, default):
    return nxt if nxt and nxt.startswith("/") and not nxt.startswith("//") else default


def ensure_candidate(patient, status="evaluation", diagnosis=None):
    c = Candidate.query.filter_by(patient_id=patient.id).first()
    if not c:
        c = Candidate(patient_id=patient.id, status=status, diagnosis=diagnosis)
        db.session.add(c)
        db.session.flush()
    return c


def portal_alerts(civil_id):
    """Activity for this Civil ID in the main (Thoracic) app and the Al-Adan portal, for the warning banner. Best effort."""
    import requests
    from flask import current_app
    base, key = current_app.config.get("MAIN_APP_URL"), current_app.config.get("PORTAL_SSO_SECRET")
    if not (base and key and civil_id):
        return []
    try:
        r = requests.get(base + "/api/portal/patient-activity", params={"civil_id": civil_id, "exclude": "ltu"},
                         headers={"X-Portal-Key": key}, timeout=3)
        return r.json().get("items", []) if r.status_code == 200 else []
    except (requests.RequestException, ValueError):
        return []
