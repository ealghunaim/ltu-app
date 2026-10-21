import os
import re

from flask import Blueprint, render_template, request, abort, send_from_directory, current_app
from flask_login import login_required

from models import db, ProtocolDoc
from core import team_required

protocols_bp = Blueprint("protocols", __name__, url_prefix="/protocols")

DOCS = [
    ("CDH-LTU-IMPL-01", "LTU Implementation Protocol", "v3.0 (2026)", "Governance, mandate, MDT, facilities, domestic transplant pathway, QAPI. Includes the MDT Transplant Decision Form."),
    ("CDH-LTU-PERIOP-02", "Perioperative Protocol", "v1.0 (April 2026)", "Admission to discharge: pre-op, implantation sequence, ICU, PGD grading, CMV, rehab, discharge criteria."),
    ("CDH-LTU-ANAES-01", "Anaesthesia Protocol", "see document", "Intra-operative anaesthesia, monitoring, ECMO/ECLS, reperfusion, analgesia, immunosuppression role."),
    ("CDH-LTU-PPO-03", "Post-operative Orders (CTICU)", "v1.0 (April 2026)", "Immediate post-operative order set: ventilation, fluids, immunosuppression, prophylaxis, analgesia."),
]


def seed_protocols(app):
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "protocols")
    for code, title, ver, summ in DOCS:
        d = ProtocolDoc.query.filter_by(code=code).first()
        txt_path = os.path.join(root, code + ".txt")
        txt = open(txt_path, encoding="utf-8", errors="ignore").read() if os.path.exists(txt_path) else ""
        if not d:
            d = ProtocolDoc(code=code)
            db.session.add(d)
        d.title, d.version, d.summary, d.filename, d.text = title, ver, summ, code + ".pdf", txt
    db.session.commit()


@protocols_bp.route("")
@login_required
def library():
    q = request.args.get("q", "").strip()
    hits = []
    if len(q) >= 3:
        pat = re.compile(re.escape(q), re.I)
        for d in ProtocolDoc.query.order_by(ProtocolDoc.code).all():
            lines = [l.strip() for l in (d.text or "").splitlines()]
            for i, l in enumerate(lines):
                if pat.search(l):
                    ctx = " ".join(x for x in lines[max(0, i - 1):i + 2] if x)
                    hits.append({"code": d.code, "title": d.title, "line": ctx[:300], "q": q})
                    if sum(1 for h in hits if h["code"] == d.code) >= 8:
                        break
    return render_template("protocols.html", docs=ProtocolDoc.query.order_by(ProtocolDoc.code).all(), q=q, hits=hits)


@protocols_bp.route("/<code>")
@login_required
def view(code):
    d = ProtocolDoc.query.filter_by(code=code).first() or abort(404)
    return render_template("protocol_view.html", d=d)


@protocols_bp.route("/<code>/pdf")
@login_required
def pdf(code):
    d = ProtocolDoc.query.filter_by(code=code).first() or abort(404)
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "protocols")
    return send_from_directory(root, d.filename, mimetype="application/pdf", as_attachment=False)
