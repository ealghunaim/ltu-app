"""CDH Lung Transplant Unit (LTU) -- standalone app."""
import os
import time
from datetime import date

from flask import Flask, redirect, url_for, request, session, flash, jsonify, render_template
from flask_login import LoginManager, current_user, logout_user

from config import Config
from models import (db, User, ROLE_ADMIN, USER_APPROVED, ROLE_LABELS, CANDIDATE_STATUS, DECISIONS, CASE_TYPES, REFERRAL_STATUS)

login_manager = LoginManager()
login_manager.login_view = "auth.login"
IDLE_GRACE = 20


def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if config:
        app.config.update(config)
    os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "instance"), exist_ok=True)
    db.init_app(app)
    login_manager.init_app(app)

    @login_manager.user_loader
    def _load(uid):
        return db.session.get(User, int(uid))

    from auth import auth_bp
    from views import main_bp
    from patients import patients_bp
    from referrals import referrals_bp
    from mdt import mdt_bp
    from episodes import episodes_bp
    from followups import followups_bp
    from protocols import protocols_bp
    for bp in (auth_bp, main_bp, patients_bp, referrals_bp, mdt_bp, episodes_bp, followups_bp, protocols_bp):
        app.register_blueprint(bp)

    @app.before_request
    def _idle():
        """HIPAA-style automatic logoff: server-side idle limit (default 15 min)."""
        limit = app.config["SESSION_IDLE_MINUTES"] * 60
        if not limit or not current_user.is_authenticated or request.path.startswith("/static/"):
            return None
        now, last = time.time(), session.get("last_active")
        if last is not None and now - float(last) > limit + IDLE_GRACE:
            logout_user()
            session.clear()
            if request.method == "GET":
                flash("You were signed out after a period of inactivity.", "warning")
                return redirect(url_for("auth.login"))
            return jsonify({"error": "session_expired"}), 401
        session["last_active"] = now

    @app.route("/keepalive", methods=["POST"])
    def keepalive():
        session["last_active"] = time.time()
        return ("", 204)

    @app.after_request
    def _headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if request.endpoint != "static":
            resp.headers["Cache-Control"] = "no-store"
        return resp

    @app.context_processor
    def _ctx():
        return dict(ROLE_LABELS=ROLE_LABELS, CANDIDATE_STATUS=CANDIDATE_STATUS, DECISIONS=DECISIONS, CASE_TYPES=CASE_TYPES,
                    REFERRAL_STATUS=REFERRAL_STATUS, idle_seconds=int(app.config["SESSION_IDLE_MINUTES"] * 60), today=date.today(), main_app_url=(app.config.get("MAIN_APP_URL") or ""),
                    has_ltu_logo=os.path.isfile(os.path.join(app.static_folder, "images", "ltu_logo.png")),
                    has_thoracic_logo=os.path.isfile(os.path.join(app.static_folder, "images", "thoracic_logo.jpg")))

    @app.errorhandler(403)
    def _403(e):
        return render_template("error.html", code=403, msg="You do not have access to that page."), 403

    @app.errorhandler(404)
    def _404(e):
        return render_template("error.html", code=404, msg="Page not found."), 404

    with app.app_context():
        db.create_all()
        _seed(app)
    return app


def _seed(app):
    pw = app.config["LTU_ADMIN_PASSWORD"]
    if not User.query.filter_by(role=ROLE_ADMIN).first() and pw:
        u = User(full_name="LTU Administrator", email=app.config["LTU_ADMIN_EMAIL"].lower(), role=ROLE_ADMIN, status=USER_APPROVED)
        u.set_password(pw)
        db.session.add(u)
        db.session.commit()
        app.logger.warning("Created first administrator %s", u.email)
    elif not User.query.filter_by(role=ROLE_ADMIN).first():
        app.logger.warning("No administrator exists: set LTU_ADMIN_PASSWORD (and LTU_ADMIN_EMAIL) and restart to create one.")
    from protocols import seed_protocols
    seed_protocols(app)


if __name__ == "__main__":
    create_app().run(debug=True, port=5100)
