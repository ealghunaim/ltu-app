"""Data model for the CDH Lung Transplant Unit (LTU) app."""
import json
from datetime import datetime, date

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()

# ---- roles -------------------------------------------------------------
ROLE_ADMIN = "admin"
ROLE_MEDICAL_DIRECTOR = "medical_director"
ROLE_SURGICAL_DIRECTOR = "surgical_director"
ROLE_PULMONOLOGIST = "transplant_pulmonologist"
ROLE_SURGEON = "transplant_surgeon"
ROLE_COORDINATOR = "coordinator"
ROLE_ANAESTHESIA = "anaesthesiologist"
ROLE_ICU = "icu_physician"
ROLE_ID = "id_physician"
ROLE_PHARMACIST = "pharmacist"
ROLE_ALLIED = "allied_health"
ROLE_REFERRING = "referring"

ROLE_LABELS = {
    ROLE_ADMIN: "Administrator", ROLE_MEDICAL_DIRECTOR: "Medical Director (Transplant Pulmonology)",
    ROLE_SURGICAL_DIRECTOR: "Surgical Director (Thoracic Surgery)", ROLE_PULMONOLOGIST: "Transplant Pulmonologist",
    ROLE_SURGEON: "Transplant / Senior Thoracic Surgeon", ROLE_COORDINATOR: "Transplant Coordinator",
    ROLE_ANAESTHESIA: "Transplant Anaesthesiologist", ROLE_ICU: "ICU Consultant / Intensivist",
    ROLE_ID: "Infectious Disease Physician", ROLE_PHARMACIST: "Transplant Pharmacist",
    ROLE_ALLIED: "Allied health (dietitian / physio / psychology / social work)",
    ROLE_REFERRING: "Referring physician (MOH hospital)",
}
TEAM_ROLES = [r for r in ROLE_LABELS if r != ROLE_REFERRING]
# Who may finalise an MDT decision / change listing status.
DECIDER_ROLES = {ROLE_ADMIN, ROLE_MEDICAL_DIRECTOR, ROLE_SURGICAL_DIRECTOR}
# Who may approve new accounts / manage users.
USER_ADMIN_ROLES = {ROLE_ADMIN, ROLE_COORDINATOR, ROLE_MEDICAL_DIRECTOR}

USER_PENDING, USER_APPROVED, USER_DISABLED = "pending", "approved", "disabled"


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(200), nullable=False)
    email = db.Column(db.String(200), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(300), nullable=False)
    role = db.Column(db.String(40), nullable=False, default=ROLE_REFERRING)
    hospital = db.Column(db.String(200))
    phone = db.Column(db.String(50))
    status = db.Column(db.String(20), default=USER_PENDING, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    @property
    def is_active(self):
        return self.status == USER_APPROVED

    @property
    def is_team(self):
        return self.role in TEAM_ROLES

    @property
    def can_decide(self):
        return self.role in DECIDER_ROLES

    @property
    def can_manage_users(self):
        return self.role in USER_ADMIN_ROLES


class _JSONMixin:
    """`data` column helpers: a JSON text blob for schema-driven form sections."""

    def get_data(self, key=None):
        try:
            d = json.loads(self.data or "{}")
        except ValueError:
            d = {}
        return d if key is None else d.get(key, {})

    def set_section(self, key, values):
        d = self.get_data()
        d[key] = values
        self.data = json.dumps(d)


class Patient(db.Model):
    __tablename__ = "patients"
    id = db.Column(db.Integer, primary_key=True)
    ltu_case_no = db.Column(db.String(30), unique=True)
    civil_id = db.Column(db.String(50), unique=True, nullable=False, index=True)
    full_name = db.Column(db.String(200), nullable=False)
    date_of_birth = db.Column(db.Date)
    sex = db.Column(db.String(20))
    nationality = db.Column(db.String(100))
    phone = db.Column(db.String(50))
    blood_group = db.Column(db.String(10))
    file_number = db.Column(db.String(50))  # CDH MRN
    source = db.Column(db.String(20), default="manual")  # manual | main_app
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def age(self):
        if not self.date_of_birth:
            return None
        t = date.today()
        return t.year - self.date_of_birth.year - ((t.month, t.day) < (self.date_of_birth.month, self.date_of_birth.day))


REFERRAL_STATUS = {"new": "New", "evaluation": "Under evaluation", "presented": "Presented at MDT", "decided": "Decision made"}


class Referral(db.Model, _JSONMixin):
    __tablename__ = "referrals"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    referring_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    institution = db.Column(db.String(200))
    referring_physician = db.Column(db.String(200))
    referral_date = db.Column(db.Date, default=date.today)
    primary_diagnosis = db.Column(db.String(300))
    reason = db.Column(db.Text)
    status = db.Column(db.String(20), default="new")
    data = db.Column(db.Text, default="{}")  # clinical parameter section(s)
    decision_sent_at = db.Column(db.DateTime)  # written decision communicated (target: within 5 working days)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("Patient")
    referring_user = db.relationship("User")


CASE_TYPES = {"new_referral": "New Referral", "waitlist_review": "Waitlist Review", "organ_offer": "Organ Offer Review",
              "post_tx_review": "Post-Tx Review", "complex": "Complex / Other"}
DECISIONS = {"list": "LIST FOR TRANSPLANT", "conditional": "CONDITIONAL LISTING", "defer": "DEFER - further workup",
             "inactive": "INACTIVE STATUS", "decline": "DECLINE / DELIST"}


class MDTCase(db.Model, _JSONMixin):
    """One row of the CDH-LTU-MDT-05 'MDT Transplant Decision Form'."""
    __tablename__ = "mdt_cases"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    referral_id = db.Column(db.Integer, db.ForeignKey("referrals.id"))
    mdt_date = db.Column(db.Date, default=date.today)
    case_type = db.Column(db.String(30), default="new_referral")
    decision = db.Column(db.String(20))
    status = db.Column(db.String(10), default="draft")  # draft | final
    chair_name = db.Column(db.String(200))
    finalised_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    finalised_at = db.Column(db.DateTime)
    next_review_date = db.Column(db.Date)
    data = db.Column(db.Text, default="{}")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("Patient")
    referral = db.relationship("Referral")
    finalised_by = db.relationship("User", foreign_keys=[finalised_by_id])
    created_by = db.relationship("User", foreign_keys=[created_by_id])


CANDIDATE_STATUS = {"evaluation": "Under evaluation", "listed": "Active - listed", "conditional": "Conditional listing",
                    "inactive": "Inactive (suspended)", "declined": "Declined", "delisted": "Delisted",
                    "transplanted": "Transplanted", "deceased": "Deceased"}
ACTIVE_STATUSES = ("evaluation", "listed", "conditional", "inactive")


class Candidate(db.Model):
    """Waitlist registry row -- one per patient."""
    __tablename__ = "candidates"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), unique=True, nullable=False)
    status = db.Column(db.String(20), default="evaluation")
    diagnosis = db.Column(db.String(300))
    listing_date = db.Column(db.Date)
    procedure_type = db.Column(db.String(20))  # BLT | SLT
    side = db.Column(db.String(10))            # right | left | either
    priority = db.Column(db.String(20))        # standard | high | urgent
    tlc_low = db.Column(db.Float)
    tlc_high = db.Column(db.Float)
    special_donor_notes = db.Column(db.Text)
    last_review_date = db.Column(db.Date)
    next_review_due = db.Column(db.Date)
    notes = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    patient = db.relationship("Patient", backref=db.backref("candidate", uselist=False))
    history = db.relationship("CandidateStatusChange", backref="candidate", order_by="CandidateStatusChange.at.desc()")


class CandidateStatusChange(db.Model):
    __tablename__ = "candidate_status_changes"
    id = db.Column(db.Integer, primary_key=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey("candidates.id"), nullable=False)
    from_status = db.Column(db.String(20))
    to_status = db.Column(db.String(20))
    reason = db.Column(db.Text)
    mdt_case_id = db.Column(db.Integer, db.ForeignKey("mdt_cases.id"))
    by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    at = db.Column(db.DateTime, default=datetime.utcnow)
    by_user = db.relationship("User")


class Episode(db.Model, _JSONMixin):
    """A transplant episode: organ offer -> admission -> OR -> ICU -> discharge."""
    __tablename__ = "episodes"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    stage = db.Column(db.String(20), default="offer")  # offer | admitted | or | icu | ward | discharged | cancelled
    offer_at = db.Column(db.DateTime)
    offer_decision = db.Column(db.String(20))  # accepted | declined | pending
    procedure = db.Column(db.String(30))  # right_slt | left_slt | bslt
    transplant_date = db.Column(db.Date)
    cross_clamp_at = db.Column(db.DateTime)
    reperfusion_at = db.Column(db.DateTime)
    discharge_date = db.Column(db.Date)
    donor_cmv = db.Column(db.String(5))
    recipient_cmv = db.Column(db.String(5))
    data = db.Column(db.Text, default="{}")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("Patient", backref="episodes")
    pgd = db.relationship("PGDAssessment", backref="episode", order_by="PGDAssessment.hours")

    @property
    def cold_ischaemic_hours(self):
        if self.cross_clamp_at and self.reperfusion_at:
            return round((self.reperfusion_at - self.cross_clamp_at).total_seconds() / 3600, 1)
        return None


class PGDAssessment(db.Model):
    __tablename__ = "pgd_assessments"
    id = db.Column(db.Integer, primary_key=True)
    episode_id = db.Column(db.Integer, db.ForeignKey("episodes.id"), nullable=False)
    hours = db.Column(db.Integer, nullable=False)  # 0 / 24 / 48 / 72
    pao2 = db.Column(db.Float)
    fio2 = db.Column(db.Float)  # fraction 0.21-1.0
    infiltrates = db.Column(db.Boolean, default=False)
    on_ecmo = db.Column(db.Boolean, default=False)
    grade = db.Column(db.Integer)
    recorded_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def pf_ratio(self):
        if self.pao2 and self.fio2:
            return round(self.pao2 / self.fio2)
        return None


class FollowUp(db.Model, _JSONMixin):
    """Post-transplant clinic visit (Year-1 months 1/3/6/9/12, annual, unscheduled)."""
    __tablename__ = "followups"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    episode_id = db.Column(db.Integer, db.ForeignKey("episodes.id"))
    visit_date = db.Column(db.Date, default=date.today, nullable=False)
    visit_type = db.Column(db.String(20), default="unscheduled")
    fev1_l = db.Column(db.Float)
    fev1_pct = db.Column(db.Float)
    fvc_l = db.Column(db.Float)
    tacrolimus = db.Column(db.Float)
    creatinine = db.Column(db.Float)
    next_visit_date = db.Column(db.Date)
    data = db.Column(db.Text, default="{}")
    created_by_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    patient = db.relationship("Patient", backref="followups")
    episode = db.relationship("Episode")


class TroughLevel(db.Model):
    """Immunosuppressant trough levels logged between visits (e.g. daily in hospital)."""
    __tablename__ = "trough_levels"
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False)
    episode_id = db.Column(db.Integer, db.ForeignKey("episodes.id"))
    drawn_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    drug = db.Column(db.String(30), default="tacrolimus")
    value = db.Column(db.Float, nullable=False)
    by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    patient = db.relationship("Patient")


class ProtocolDoc(db.Model):
    __tablename__ = "protocol_docs"
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(40), unique=True, nullable=False)
    title = db.Column(db.String(300), nullable=False)
    version = db.Column(db.String(60))
    summary = db.Column(db.Text)
    filename = db.Column(db.String(200))
    text = db.Column(db.Text)


class AuditLog(db.Model):
    __tablename__ = "audit_log"
    id = db.Column(db.Integer, primary_key=True)
    at = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"))
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"))
    action = db.Column(db.String(60))
    detail = db.Column(db.Text)
    user = db.relationship("User")
    patient = db.relationship("Patient")
