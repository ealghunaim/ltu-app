"""LTU app end-to-end tests. Run: python test_ltu.py"""
import os, sys, tempfile, re
from datetime import date, timedelta
_db = tempfile.mktemp(suffix=".db")
os.environ.update(DATABASE_URL="sqlite:///" + _db, LTU_ADMIN_PASSWORD="Admin#12345", LTU_ADMIN_EMAIL="admin@x.org", SECRET_KEY="k", SESSION_IDLE_MINUTES="15", PORTAL_SSO_SECRET="sharedsecret", MAIN_APP_URL="https://main.example.com")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app import create_app
from models import db, Patient, Referral, MDTCase, Candidate, Episode, FollowUp, User, PGDAssessment
from schemas import pgd_grade, tac_target, fev1_drop_pct, cmv_advice

fails = 0
def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails += 1

app = create_app()
def client(): return app.test_client()
def login(c, e, p): return c.post("/login", data={"email": e, "password": p}, follow_redirects=False)

# --- pure logic
check("PGD g0", pgd_grade(350, True, False) == 0)
check("PGD g1", pgd_grade(250, True, False) == 1)
check("PGD g2", pgd_grade(150, True, False) == 2)
check("PGD g3", pgd_grade(80, True, False) == 3)
check("PGD ecmo=3", pgd_grade(400, True, True) == 3)
check("tac target m2", tac_target(2) == (10, 15) or tuple(tac_target(2)) == (10, 15))
check("tac target m6", tuple(tac_target(6)) == (8, 12))
check("fev1 drop", fev1_drop_pct(3.0, 2.4) == 20.0)
check("cmv D+R-", "HIGHEST" in cmv_advice("pos", "neg"))

admin = client(); r = login(admin, "admin@x.org", "Admin#12345"); check("admin login", r.status_code == 302)
r = admin.post("/users/new", data={"full_name": "Dr Pulm", "email": "pulm@x.org", "password": "Passw0rd!!", "role": "transplant_pulmonologist"}); check("create team user", r.status_code in (200, 302))
# referring self-register -> pending -> cannot login -> approve
ref = client()
r = ref.post("/register", data={"full_name": "Dr Ref", "email": "ref@x.org", "password": "Passw0rd!!", "hospital": "Mubarak", "phone": "1"}, follow_redirects=True)
check("register ok", r.status_code == 200)
r = login(ref, "ref@x.org", "Passw0rd!!"); r2 = ref.get("/referrals/new")
check("pending cannot access", r2.status_code in (302, 401, 403))
with app.app_context():
    uid = User.query.filter_by(email="ref@x.org").first().id
r = admin.post(f"/users/{uid}/update", data={"action": "approve"}); check("approve", r.status_code in (200, 302))
r = login(ref, "ref@x.org", "Passw0rd!!"); check("referrer login", r.status_code == 302)
check("referrer dashboard", ref.get("/").status_code == 200)
check("referrer blocked from candidates", ref.get("/candidates").status_code == 403)
check("referrer blocked from patients", ref.get("/patients").status_code == 403)
check("referrer blocked from episodes", ref.get("/episodes").status_code == 403)
check("referrer blocked from audit", ref.get("/audit").status_code in (403, 302))

# --- team self sign-up
tm = client()
check("login page offers both sign-ups", b"LTU team member" in tm.get("/login").data and b"Referring physician" in tm.get("/login").data)
check("team register page", b"Role" in tm.get("/register?kind=team").data)
r = tm.post("/register", data={"kind": "team", "full_name": "Dr Anaes", "role": "anaesthesiologist", "email": "an@x.org", "password": "Passw0rd!!"}, follow_redirects=True)
check("team signup ok", r.status_code == 200 and b"approve" in r.data)
r = login(tm, "an@x.org", "Passw0rd!!"); check("team pending cannot use app", tm.get("/patients").status_code in (302, 401, 403))
r = tm.post("/register", data={"kind": "team", "full_name": "Evil", "role": "admin", "email": "ev@x.org", "password": "Passw0rd!!"}, follow_redirects=True)
with app.app_context(): check("cannot self-register as admin", User.query.filter_by(email="ev@x.org").first() is None)
with app.app_context(): au = User.query.filter_by(email="an@x.org").first(); check("team user pending w/ role", au.status == "pending" and au.role == "anaesthesiologist"); auid = au.id
admin.post(f"/users/{auid}/update", data={"action": "approve"})
login(tm, "an@x.org", "Passw0rd!!"); check("approved team user in", tm.get("/patients").status_code == 200)

# --- referral: minor rejected, adult ok
base = {"civil_id": "290010100001", "full_name": "Test Patient", "sex": "Male", "primary_diagnosis": "IPF", "reason": "End-stage ILD"}
r = ref.post("/referrals/new", data={**base, "civil_id": "311010100002", "full_name": "Kid", "date_of_birth": (date.today() - timedelta(days=365 * 10)).isoformat()})
check("minor rejected", r.status_code == 400)
r = ref.post("/referrals/new", data={**base, "date_of_birth": "1970-01-01", "clinical__fev1_pct": "30"}, follow_redirects=False)
check("adult referral created", r.status_code == 302)
with app.app_context():
    rf = Referral.query.first(); pid = rf.patient_id; rid = rf.id
    check("candidate created", Candidate.query.filter_by(patient_id=pid).first() is not None)
check("referrer sees own referral", ref.get(f"/referrals/{rid}").status_code == 200)
# another referrer cannot see
o = client(); admin.post("/users/new", data={"full_name": "Other", "email": "o@x.org", "password": "Passw0rd!!", "role": "referring"}); login(o, "o@x.org", "Passw0rd!!")
check("other referrer 403", o.get(f"/referrals/{rid}").status_code == 403)

team = client(); login(team, "pulm@x.org", "Passw0rd!!")
check("team sees referral", team.get(f"/referrals/{rid}").status_code == 200)
r = team.get(f"/mdt/new?patient_id={pid}&referral_id={rid}", follow_redirects=False); check("mdt created", r.status_code == 302)
mid = int(r.headers["Location"].rstrip("/").split("/")[-1])
check("mdt form renders", team.get(f"/mdt/{mid}").status_code == 200)
r = team.post(f"/mdt/{mid}", data={"mdt_date": date.today().isoformat(), "case_type": "new_referral", "decision": "list", "chair_name": "Dr Chair",
              "next_review": "3m", "listing__procedure_type": "BLT", "listing__priority": "standard"}, follow_redirects=False)
check("mdt saved", r.status_code == 302)
team.post(f"/mdt/{mid}/finalise")
with app.app_context(): check("pulmonologist cannot finalise", db.session.get(MDTCase, mid).status == "draft")
check("director/admin can finalise", admin.post(f"/mdt/{mid}/finalise").status_code == 302)
with app.app_context():
    c = Candidate.query.filter_by(patient_id=pid).first(); m = db.session.get(MDTCase, mid)
    check("candidate listed", c.status == "listed"); check("mdt final", m.status == "final"); check("procedure carried", c.procedure_type == "BLT")
    check("next review set", c.next_review_due is not None)
# referrer cannot see decision until sent
check("decision hidden before sent", b"MDT decision" not in ref.get(f"/referrals/{rid}").data)
check("letter hidden before sent", ref.get(f"/referrals/{rid}/letter").status_code == 404)
check("final form not editable", b"cannot be edited" in admin.post(f"/mdt/{mid}", data={"decision": "decline"}, follow_redirects=True).data)
team.post(f"/referrals/{rid}/status", data={"mark_sent": "1"})
check("decision visible after sent", b"MDT decision" in ref.get(f"/referrals/{rid}").data)
check("letter ok", ref.get(f"/referrals/{rid}/letter").status_code == 200)
check("mdt print", team.get(f"/mdt/{mid}/print").status_code == 200)
check("referrer cannot open mdt", ref.get(f"/mdt/{mid}").status_code == 403)

# --- episode gates
r = team.post("/episodes/new", data={"patient_id": pid}, follow_redirects=False); eid = int(r.headers["Location"].rstrip("/").split("/")[-1])
check("episode page", team.get(f"/episodes/{eid}").status_code == 200)
team.post(f"/episodes/{eid}/stage", data={"stage": "admitted"})
with app.app_context(): check("cannot admit before accept", db.session.get(Episode, eid).stage == "offer")
team.post(f"/episodes/{eid}/core", data={"offer_decision": "accepted", "procedure": "bslt", "donor_cmv": "pos", "recipient_cmv": "neg",
          "cross_clamp_at": "2026-10-20T01:00", "reperfusion_at": "2026-10-20T08:30"})
team.post(f"/episodes/{eid}/stage", data={"stage": "admitted"}); team.post(f"/episodes/{eid}/stage", data={"stage": "or"}); team.post(f"/episodes/{eid}/stage", data={"stage": "icu"})
with app.app_context():
    e = db.session.get(Episode, eid); check("stage icu", e.stage == "icu"); check("CIT 7.5h", e.cold_ischaemic_hours == 7.5)
    check("candidate transplanted", Candidate.query.filter_by(patient_id=pid).first().status == "transplanted")
check("episode page w/ data", team.get(f"/episodes/{eid}").status_code == 200)
team.post(f"/episodes/{eid}/pgd", data={"hours": "24", "pao2": "150", "fio2": "1.0", "infiltrates": "on"})
with app.app_context(): check("pgd grade 2", PGDAssessment.query.filter_by(episode_id=eid).first().grade == 2)
check("pgd warning shown", b"PGD grade 2" in team.get(f"/episodes/{eid}").data)
team.post(f"/episodes/{eid}/trough", data={"value": "7"}); 
team.post(f"/episodes/{eid}/section/offer/offer", data={"offer__donor_age": "30"})
team.post(f"/episodes/{eid}/stage", data={"stage": "ward"})
team.post(f"/episodes/{eid}/stage", data={"stage": "discharged"})
with app.app_context(): check("discharge gate blocks", db.session.get(Episode, eid).stage == "ward")
from schemas import DISCHARGE_GATE
team.post(f"/episodes/{eid}/section/discharge/discharge_gate", data={f"discharge_gate__{k}": "on" for k, _ in DISCHARGE_GATE})
team.post(f"/episodes/{eid}/stage", data={"stage": "discharged"})
with app.app_context(): check("discharged after gate", db.session.get(Episode, eid).stage == "discharged")

# --- follow-up
check("followup list", team.get("/followups").status_code == 200)
check("followup form", team.get(f"/patients/{pid}/followups/new?type=month1").status_code == 200)
r = team.post(f"/patients/{pid}/followups/new?type=month1", data={"visit_date": date.today().isoformat(), "fev1_l": "2.0", "tacrolimus": "5", "vitals__home_spiro_baseline": "3.0", "vitals__home_spiro_latest": "2.4"}, follow_redirects=True)
check("followup saved + warnings", r.status_code == 200 and b"outside the target" in r.data and b"below personal best" in r.data)
with app.app_context(): fid = FollowUp.query.first().id
check("followup view", team.get(f"/followups/{fid}").status_code == 200)
check("patient detail w/ charts", b"<svg" in team.get(f"/patients/{pid}").data)

# --- print views
for u, name in [(f"/print/patient/{pid}", "patient"), (f"/print/referral/{rid}", "referral"), (f"/print/episode/{eid}", "episode"), (f"/print/followup/{fid}", "followup"),
                ("/print/waitlist", "waitlist"), ("/print/waitlist?status=all", "waitlist all"), ("/print/followups", "followup schedule"), (f"/print/mdt-agenda?date={date.today().isoformat()}", "mdt agenda")]:
    r = team.get(u); check("print " + name + " renders", r.status_code == 200 and b"Lung Transplant Unit" in r.data and b"Confidential patient information" in r.data)
check("print patient has data", b"Test Patient" in team.get(f"/print/patient/{pid}").data and b"290010100001" in team.get(f"/print/patient/{pid}").data)
check("print episode shows PGD + CIT", b"7.5 h" in team.get(f"/print/episode/{eid}").data and b"ISHLT" in team.get(f"/print/episode/{eid}").data)
check("print followup flags out-of-range tac", b"OUT OF RANGE" in team.get(f"/print/followup/{fid}").data)
check("referrer can print own referral", ref.get(f"/print/referral/{rid}").status_code == 200)
check("other referrer cannot print it", o.get(f"/print/referral/{rid}").status_code == 403)
check("referrer cannot print patient/episode/waitlist", all(ref.get(u).status_code == 403 for u in (f"/print/patient/{pid}", f"/print/episode/{eid}", "/print/waitlist")))
check("print buttons on pages", b"Print summary" in team.get(f"/patients/{pid}").data and b"Print record" in team.get(f"/episodes/{eid}").data and b"Print list" in team.get("/candidates").data
      and b"Print schedule" in team.get("/followups").data and b"Print agenda" in team.get("/mdt").data and b"Print visit" in team.get(f"/followups/{fid}").data and b"Print referral" in team.get(f"/referrals/{rid}").data)
with app.app_context():
    from models import AuditLog
    check("prints are audit-logged", AuditLog.query.filter(AuditLog.action.like("%_printed")).count() >= 7)

# --- misc
check("protocol search", b"CDH-LTU" in team.get("/protocols?q=tacrolimus").data)
check("protocol pdf", team.get("/protocols/CDH-LTU-IMPL-01/pdf").status_code == 200)
check("lookup local", team.get("/patients/lookup?civil_id=290010100001").json["found"] is True)
check("lookup unknown (no main app)", team.get("/patients/lookup?civil_id=999").json["found"] is False)
check("anon redirected", client().get("/candidates").status_code in (302, 401))
check("referrer lookup blocked for unknown", ref.get("/patients/lookup?civil_id=999").json["found"] is False)
check("audit visible to admin", admin.get("/audit").status_code == 200)

# --- round 2 (2026-10-24): SSO, Today board, status API, cross-portal alerts
from itsdangerous import URLSafeTimedSerializer
from unittest import mock
ser = URLSafeTimedSerializer("sharedsecret", salt="portal-sso")
def tok(**kw):
    d = {"email": "sso@x.org", "name": "Dr Sso", "phone": "55", "hospital": "Mubarak", "role": "referring", "portal": "ltu", "next": ""}
    d.update(kw); return ser.dumps(d)
s1 = client(); r = s1.get("/sso?token=" + tok())
check("sso referring login", r.status_code == 302 and b"Submit a referral" in s1.get("/").data)
with app.app_context(): u = User.query.filter_by(email="sso@x.org").first(); check("sso user approved referring", u.role == "referring" and u.status == "approved" and u.hospital == "Mubarak")
s2 = client(); s2.get("/sso?token=" + tok(email="ts@x.org", name="Dr TS", role="transplant_surgeon"))
check("sso surgeon is team", s2.get("/candidates").status_code == 200 and s2.get("/today").status_code == 200)
check("sso bad token", client().get("/sso?token=bad").status_code == 302)
check("sso wrong portal", client().get("/sso?token=" + tok(portal="adan")).status_code == 400)
with app.app_context(): before = User.query.filter_by(role="admin").first().role
s3 = client(); s3.get("/sso?token=" + tok(email="admin@x.org", role="referring"))
with app.app_context(): check("sso never downgrades native admin", User.query.filter_by(email="admin@x.org").first().role == "admin")
check("sso open redirect blocked", "evil.com" not in client().get("/sso?token=" + tok(email="e@x.org", next="//evil.com")).headers["Location"])
check("today board renders", b"Today board" in team.get("/today").data)
r = team.get("/today/print"); check("today print", r.status_code == 200 and b"handover" in r.data.lower())
check("today blocked for referrer", ref.get("/today").status_code == 403)
check("status api needs key", client().get("/api/main/patient-status?civil_id=290010100001").status_code == 403)
with app.app_context():
    _p = Patient(civil_id="291111111111", full_name="Active Pt"); db.session.add(_p); db.session.flush()
    db.session.add(Candidate(patient_id=_p.id, status="listed", diagnosis="IPF")); db.session.add(Referral(patient_id=_p.id, status="new", primary_diagnosis="IPF")); db.session.commit()
j = client().get("/api/main/patient-status?civil_id=291111111111", headers={"X-Portal-Key": "sharedsecret"}).json
check("status api reports candidate + referral " + str(j), j["found"] and len(j["items"]) == 2 and j["items"][0]["status"] == "Active - listed")
check("status api unknown", client().get("/api/main/patient-status?civil_id=000", headers={"X-Portal-Key": "sharedsecret"}).json == {"found": False, "items": []})
class _R:
    status_code = 200
    def json(s): return {"items": [{"portal": "adan", "label": "Al-Adan Respirology consult AC-1", "status": "Waiting", "detail": "Effusion"}]}
with mock.patch("requests.get", return_value=_R()) as g:
    with app.app_context(): pid = Patient.query.filter_by(civil_id="290010100001").first().id
    html = team.get(f"/patients/{pid}").data
    check("alert banner on patient page", b"already active elsewhere" in html and b"Al-Adan Respirology" in html)
    check("alert excludes ltu + key", g.call_args.kwargs["params"]["exclude"] == "ltu" and g.call_args.kwargs["headers"] == {"X-Portal-Key": "sharedsecret"})
# idle logout
with team.session_transaction() as s: s["last_active"] = 0
r = team.get("/candidates"); check("idle logout", r.status_code in (302, 401))
for sk in ["/ping"]: pass
print("\nFAILS:", fails); sys.exit(1 if fails else 0)
