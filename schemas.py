"""Schema-driven forms + protocol rules (CDH-LTU-IMPL-01 / PERIOP-02 / PPO-03 / ANAES-01).

A form is a list of sections; a section is (key, title, [fields]).  A field is a dict:
  name, label, type in {text, textarea, number, date, datetime, select, yesno, check, multi, readonly}
  options=[(value,label)], help, step (number), wide (full-width)
The generic renderer (templates/_form.html) and parser (parse_section) use these, so every
clinical form in the app is defined once, here.
"""
from datetime import datetime, date

YN = [("yes", "Yes"), ("no", "No")]


def F(name, label, type="text", options=None, help=None, step=None, wide=False):
    return dict(name=name, label=label, type=type, options=options or [], help=help, step=step, wide=wide)


def parse_section(fields, form, prefix=""):
    """Pull one section's values out of request.form -> plain dict (strings / lists / bools)."""
    out = {}
    for f in fields:
        n, t = f["name"], f["type"]
        k = prefix + n
        if t == "check":
            out[n] = form.get(k) == "on"
        elif t == "multi":
            out[n] = form.getlist(k)
        elif t == "readonly":
            continue
        else:
            out[n] = (form.get(k) or "").strip()
    return out


# ---------------------------------------------------------------- referral
REFERRAL_CLINICAL = [
    ("clinical", "Clinical parameters (most recent)", [
        F("aetiology", "Underlying aetiology / subtype"), F("disease_duration", "Disease duration"),
        F("fev1_pct", "FEV1 (% pred)", "number", step="0.1"), F("fvc_pct", "FVC (% pred)", "number", step="0.1"),
        F("dlco_pct", "DLCO (% pred)", "number", step="0.1"), F("tlc_pct", "TLC (% pred)", "number", step="0.1"),
        F("sixmwt_m", "6MWT (m)", "number"), F("spo2_rest", "SpO2 rest (%)", "number"), F("spo2_exertion", "SpO2 exertion (%)", "number"),
        F("o2_requirement", "O2 requirement (L/min)"), F("mmrc", "mMRC / NYHA class"), F("mpap", "mPAP (mmHg)", "number"),
        F("smoking", "Smoking history"), F("current_therapy", "Current therapy", "textarea", wide=True),
        F("comorbidities", "Comorbidities", "textarea", wide=True),
        F("notes", "Additional clinical notes", "textarea", wide=True),
    ]),
]

# ---------------------------------------------------------------- MDT decision form (CDH-LTU-MDT-05)
_EVAL_DOMAINS = [("cardiac", "Cardiac (Echo / RHC)"), ("renal", "Renal function"), ("hepatic", "Hepatic function"),
                 ("haematology", "Haematology"), ("microbiology", "Microbiology / MDR status"), ("oncology", "Oncology screen"),
                 ("nutrition", "Nutritional assessment (BMI)"), ("functional", "Functional / rehab status"),
                 ("psychosocial", "Psychosocial / psychiatric"), ("social", "Social support"),
                 ("radiology", "Radiology (HRCT / V-Q)"), ("immunology", "Immunology / PRA / DSA")]
ABSOLUTE_CI = [("malignancy", "Active or recently treated malignancy (<2 yrs, histology-dependent)"),
               ("infection", "Uncontrolled extrapulmonary infection"),
               ("substance", "Active substance abuse or non-adherence"),
               ("organ_dysfunction", "Severe irreversible dysfunction of major organ (renal, hepatic, cardiac)"),
               ("no_support", "Absence of adequate psychosocial support"),
               ("nonadherence", "Documented, persistent non-adherence to medical therapy")]
RELATIVE_CI = [("osteoporosis", "Severe osteoporosis with vertebral fractures"), ("bmi", "BMI >35 kg/m2 or <17 kg/m2"),
               ("mech_vent", "Mechanical ventilation (non-bridging)"),
               ("resistant", "Highly resistant / untreatable pathogen (e.g. B. cenocepacia, M. abscessus)"),
               ("psychiatric", "Significant psychiatric disorder - undertreated"), ("frailty", "Frailty / poor functional reserve (SPPB <=6)")]
MDT_MEMBERS = [("surgical_director", "Surgical Director (Thoracic Surgery) - Chair"), ("medical_director", "Medical Director (Transplant Pulmonology)"),
               ("coordinator", "Transplant Coordinator"), ("pharmacy", "Pharmacy"), ("id", "Infectious Disease"),
               ("anaesthesia", "Transplant Anaesthesiology"), ("social", "Social Work / Psychology"), ("invited", "Additional / invited specialist")]
ATTEND = [("present", "Present"), ("remote", "Remote"), ("absent", "Absent")]
NEXT_REVIEW = [("1w", "1 week"), ("1m", "1 month"), ("3m", "3 months"), ("6m", "6 months"), ("date", "Specific date")]

MDT_FORM = [
    ("summary", "C. Clinical summary", [
        F("primary_diagnosis", "Primary diagnosis"), F("disease_duration", "Disease duration"), F("aetiology", "Underlying aetiology / subtype"),
        F("fev1_pct", "FEV1 (% pred)", "number", step="0.1"), F("fvc_pct", "FVC (% pred)", "number", step="0.1"),
        F("dlco_pct", "DLCO (% pred)", "number", step="0.1"), F("tlc_pct", "TLC (% pred)", "number", step="0.1"),
        F("sixmwt_m", "6MWT (m)", "number"), F("spo2_rest", "SpO2 rest", "number"), F("spo2_exertion", "SpO2 exertion", "number"),
        F("o2_requirement", "O2 requirement"), F("nyha", "NYHA / mMRC class"), F("mpap", "mPAP (mmHg)", "number"),
        F("who_unos", "WHO / UNOS Dx category"),
    ]),
    ("evaluation", "D. Multidisciplinary evaluation summary", [F(k, l, "textarea") for k, l in _EVAL_DOMAINS]),
    ("absolute_ci", "E. Absolute contraindications - present?", [F(k, l, "yesno") for k, l in ABSOLUTE_CI]),
    ("relative_ci", "E. Relative contraindications / concerns - present?", [F(k, l, "yesno") for k, l in RELATIVE_CI]),
    ("discussion", "F. MDT discussion summary", [F("summary", "Key points raised, concerns discussed, specialist input", "textarea", wide=True)]),
    ("listing", "G. If listed - transplant specification", [
        F("procedure_type", "Procedure type", "select", [("BLT", "Bilateral (BLT)"), ("SLT", "Single (SLT)")]),
        F("side", "Side (if SLT)", "select", [("right", "Right"), ("left", "Left"), ("either", "Either")]),
        F("priority", "Priority / urgency", "select", [("standard", "Standard"), ("high", "High"), ("urgent", "Urgent")]),
        F("tlc_low", "Recipient size - TLC from (L)", "number", step="0.1"), F("tlc_high", "TLC to (L)", "number", step="0.1"),
        F("special_donor", "Special donor considerations / restrictions", "textarea", wide=True),
        F("rationale", "If conditional / deferred / declined - rationale & conditions", "textarea", wide=True),
        F("review_trigger", "Re-review date / trigger"),
    ]),
    ("actions", "H. Action items & follow-up", sum([[F(f"action_{i}", f"Action {i}"), F(f"person_{i}", f"Responsible {i}"),
                                                     F(f"target_{i}", f"Target date {i}", "date"), F(f"done_{i}", f"Done {i}", "check")]
                                                    for i in range(1, 6)], [])),
    ("attendance", "J. MDT attendance", [F(k, l, "select", ATTEND) for k, l in MDT_MEMBERS]),
]

# ---------------------------------------------------------------- episode forms
EPISODE_OFFER = [
    ("offer", "Donor offer & activation (IMPL-01 section 6.5)", [
        F("kts_notified_at", "KTS contacted LTU coordinator at", "datetime"), F("donor_ref", "KTS / donor reference"),
        F("donor_age", "Donor age", "number"), F("donor_sex", "Donor sex", "select", [("M", "Male"), ("F", "Female")]),
        F("donor_blood_group", "Donor blood group"), F("donor_cause", "Cause of brain death"),
        F("donor_pao2", "Donor PaO2 / FiO2 1.0", "number"), F("donor_cxr", "Donor CXR"), F("donor_bronchoscopy", "Donor bronchoscopy / direct inspection", "textarea", wide=True),
        F("ecd", "Extended-criteria donor (ECD)?", "yesno"), F("evlp_standby", "EVLP team on standby?", "yesno"),
        F("decision_at", "Accept / decline communicated to KTS at (target <2 h)", "datetime"), F("decision_by", "Decided by"),
        F("recipient_contacted_at", "Recipient contacted at", "datetime"), F("recipient_arrival_at", "Recipient arrived CDH at", "datetime"),
        F("procurement_team_departed_at", "Procurement team departed", "datetime"),
        F("notes", "Notes", "textarea", wide=True),
    ]),
]

PREOP_CHECKLIST = [("stat_labs", "STAT CBC + diff, CMP, coagulation (PT/INR/PTT), viral serologies, Type & Crossmatch (PRBC, FFP, platelets prepared)"),
                   ("ecg_cxr", "STAT 12-lead ECG and upright CXR"), ("npo", "Strict NPO enforced"),
                   ("exam", "Full physical examination - respiratory focus; active-infection signs documented"),
                   ("consent", "Informed consent: transplant procedure and possible ECMO/CPB"),
                   ("anticoag", "Standard anticoagulants withheld"),
                   ("induction_prepared", "Induction immunosuppression prepared (basiliximab / alemtuzumab)"),
                   ("coordinator_cit", "Transplant coordinator notified; cold-ischaemia clock confirmed; OR team readiness relayed"),
                   ("isolation", "Admitted to pre-transplant / thoracic isolation unit")]
EPISODE_PREOP = [
    ("preop", "Day 0 - admission & pre-operative preparation (PERIOP-02 1.1)", [F(k, l, "check", wide=True) for k, l in PREOP_CHECKLIST] + [
        F("weight_kg", "Weight (kg)", "number", step="0.1"), F("height_cm", "Height (cm)", "number"), F("allergies", "Allergies"),
        F("recipient_cmv", "Recipient CMV serostatus", "select", [("pos", "Positive"), ("neg", "Negative")]),
        F("crossmatch_units", "Units prepared (PRBC/FFP/plt)"), F("notes", "Notes", "textarea", wide=True),
    ]),
]

EPISODE_INTRAOP = [
    ("intraop_team", "Team & timings", [
        F("surgeon", "Lead transplant surgeon"), F("assistant", "Senior thoracic surgeon (assist)"), F("anaesthesiologist", "Transplant anaesthesiologist"),
        F("perfusionist", "Perfusionist"), F("incision_time", "Skin incision", "datetime"), F("end_time", "End of surgery", "datetime"),
        F("incision", "Incision", "select", [("clamshell", "Bilateral anterolateral thoracotomy (clamshell)"), ("posterolateral", "Posterolateral thoracotomy")]),
        F("position", "Position", "select", [("supine", "Supine, arms extended"), ("lateral", "Lateral decubitus")]),
    ]),
    ("intraop_anaes", "Anaesthesia & monitoring (ANAES-01)", [
        F("dlt_confirmed", "Left DLT with bronchoscopic confirmation", "check"), F("art_line", "Arterial line", "check"), F("cvc", "CVC", "check"),
        F("pa_catheter", "PA catheter (continuous SvO2)", "check"), F("tee", "Continuous TEE", "check"),
        F("airway", "Airway", "select", [("dlt", "Double-lumen tube"), ("slt", "Single-lumen ETT")]),
        F("induction_type", "Induction", "select", [("standard", "Standard (non-PAH)"), ("pah", "High-risk / PAH protocol")]),
        F("analgesia", "Analgesia", "select", [("tea", "Thoracic epidural"), ("espb", "Bilateral ESPB"), ("pca", "Fentanyl PCA"), ("other", "Other")]),
        F("blood_products", "Blood products given"), F("fluids_ml", "Crystalloid (mL)", "number"), F("uop_ml", "Urine output (mL)", "number"),
    ]),
    ("intraop_ecls", "ECLS (ANAES-01 section 7)", [
        F("ecls_ready", "ECLS readiness confirmed (central V-A preferred)", "check"),
        F("ecls_type", "Support used", "select", [("none", "No bypass used"), ("va_intraop", "VA-ECMO (intra-op; decannulated)"), ("va_continuing", "VA-ECMO continuing to ICU"), ("cpb", "CPB used")]),
        F("cannulation", "Cannulation", "select", [("none", "None"), ("peripheral", "Peripheral (femoral)"), ("central", "Central")]),
        F("ecls_start", "ECLS start", "datetime"), F("ecls_end", "ECLS end", "datetime"), F("heparin", "Heparin / ACT management"),
    ]),
    ("intraop_surgery", "Implantation (PERIOP-02 2.3, posterior-to-anterior)", [
        F("native_pneumonectomy", "Native pneumonectomy done; pleural fluid sent for culture", "check", wide=True),
        F("bronchial", "Bronchial anastomosis (4-0 PDS) completed; wrap if ischaemic risk high", "check", wide=True),
        F("pa", "PA anastomosis (5-0 Prolene), anterior aspect left loose, flushed", "check", wide=True),
        F("la", "LA cuff anastomosis (4-0 Prolene) completed", "check", wide=True),
        F("deairing", "Retrograde de-airing before final LA knot", "check", wide=True),
        F("gradual_reperfusion", "Gradual reperfusion over 10-15 minutes", "check", wide=True),
        F("methylpred", "Methylprednisolone 500 mg IV before full reperfusion", "check", wide=True),
        F("induction_given", "Induction agent given", "select", [("basiliximab", "Basiliximab"), ("alemtuzumab", "Alemtuzumab"), ("none", "None")]),
        F("induction_time", "Induction time", "datetime"),
        F("graft_appearance", "Graft: expansion / compliance / colour", "textarea", wide=True),
        F("peribronchial_wrap", "Peribronchial wrap / flap used"), F("complications", "Intra-operative complications / events", "textarea", wide=True),
        F("cold_ischaemia_note", "Cold ischaemic time notes (target <=6 h BLT, <=8 h SLT)"),
    ]),
]

_ICU_CHECKS = [
    ("admit_isolation", "Admit to CTICU - STRICT ISOLATION single room"),
    ("notified", "Notified: transplant coordinator, transplant physician on call, respiratory therapy, physiotherapy"),
    ("keep_dry", "Keep dry: CVP <8 mmHg, MAP 65-80 mmHg, vasopressor preferred over fluid boluses"),
    ("abg", "ABG q4h and 30 min after any ventilator change"), ("toilet", "Aggressive pulmonary toilet; chest physio q4h while intubated"),
    ("bronch_d1", "Routine bedside bronchoscopy Day 1"), ("iv_d5w", "D5W 30 mL/hr KVO"),
    ("tac_trough", "Tacrolimus 12-h trough daily at 06:00"), ("id_consult", "Transplant ID consult within 24 h"),
    ("tmp_smx", "TMP-SMX SS daily (PCP, lifelong)"), ("ppi", "Pantoprazole 40 mg IV daily"),
    ("no_nsaids", "NO NSAIDs (nephrotoxic with CNI) - absolute"), ("paracetamol", "Paracetamol 1 g IV q6h scheduled"),
    ("daily_labs", "Daily labs: CBC/diff, CMP, Mg, Phos, PT/INR, PTT; daily CXR; ECG daily x3"),
    ("cmv_pcr", "CMV PCR day 7, weekly x4, then monthly to 12 months"), ("scd", "SCDs bilaterally from admission"),
    ("heparin_sc", "Heparin 5000 U SC q8h from POD1 when chest-tube drainage <50 mL/hr"),
    ("glucose", "Blood glucose q4h; insulin sliding scale; target 6-10 mmol/L"),
    ("electrolytes", "Replace Mg/Phos; K >=4.0 mmol/L (tacrolimus Mg wasting)"),
    ("dietitian", "Dietitian consult within 24 h; no grapefruit/pomelo; 25-30 kcal/kg/day"),
    ("social_work", "Social work consult from Day 3"),
    ("physio", "Early mobilisation per PPO section 10"), ("foley", "Foley to gravity; hourly UOP; notify if <0.5 mL/kg/hr"),
    ("chest_tubes", "Chest tubes -20 cmH2O; notify surgeon if >150 mL/hr x2 h"),
]
EPISODE_ICU = [
    ("icu_orders", "CDH-LTU-PPO-03 - Post-operative orders (valid 24 h; rewrite daily)", [
        F("order_at", "Orders written at", "datetime"), F("weight_kg", "Weight (kg)", "number", step="0.1"),
        F("vent_mode", "Ventilator mode"), F("vent_tv", "TV (mL/kg donor IBW) - target 6"), F("vent_peep", "PEEP (target 5-8)"), F("vent_fio2", "FiO2 (lowest for SpO2 >=94%)"),
        F("vasopressor", "Vasopressor", "select", [("norepinephrine", "Norepinephrine (first line)"), ("epinephrine", "Epinephrine (refractory RV failure)"), ("none", "None")]),
        F("furosemide", "Furosemide dose / frequency"),
        F("induction", "Induction", "select", [("basiliximab", "Basiliximab 20 mg IV POD 0 and POD 4"), ("alemtuzumab", "Alemtuzumab 30 mg IV POD 0"), ("other", "Other / as directed")]),
        F("methylpred", "Methylprednisolone dose (mg IV q8h)"), F("tacrolimus", "Tacrolimus dose (mg BID, route)"), F("tac_target", "Tacrolimus target trough (ng/mL)"),
        F("mmf", "Mycophenolate 1000 mg BID IV/PO (or other)"),
        F("antibacterial", "Antibacterial", "select", [("tazocin", "Piperacillin/tazobactam"), ("meropenem", "Meropenem"), ("vancomycin", "Vancomycin"), ("other", "Other")]),
        F("antifungal", "Antifungal", "select", [("vori", "Voriconazole 200 mg IV BID"), ("inh_ampho", "Inhaled amphotericin B"), ("other", "Other")]),
        F("cmv_agent", "CMV prophylaxis", "select", [("valgan", "Valganciclovir 900 mg PO daily"), ("ganciclovir", "IV ganciclovir 5 mg/kg daily"), ("acyclovir", "Acyclovir (D-/R-)")]),
        F("analgesia", "Analgesia", "select", [("tea", "Thoracic epidural"), ("espb", "Bilateral ESPB"), ("pca", "Fentanyl PCA")]),
        F("tubes", "Chest tubes in situ", "multi", [("right", "Right pleural"), ("left", "Left pleural"), ("mediastinal", "Mediastinal")]),
        F("prescriber", "Prescribing physician"), F("pharmacist", "Pharmacy verification"), F("nurse", "Nursing check (RN)"),
    ] + [F(k, l, "check", wide=True) for k, l in _ICU_CHECKS] + [F("notes", "Notes", "textarea", wide=True)]),
]

DISCHARGE_GATE = [("ambulatory", "Ambulatory independently or with baseline assistance"),
                  ("sat", "Acceptable O2 saturation on room air (or safe stable supplemental O2 baseline)"),
                  ("wounds", "Incisions healing, no signs of infection"),
                  ("tac48", "Therapeutic tacrolimus trough documented for >=48 consecutive hours"),
                  ("spirometry", "Stable spirometry (FEV1 >=50% predicted or acceptable post-op baseline)"),
                  ("afebrile", "Afebrile >=48 h without new antibiotics"),
                  ("clinic_7d", "Outpatient transplant clinic appointment confirmed within 7 days"),
                  ("rehab", "Outpatient pulmonary rehabilitation booked"), ("bronch_1m", "1-month bronchoscopy scheduled"),
                  ("educated", "Patient and caregiver educated on medications, monitoring, warning symptoms")]
EDUCATION = [("adherence", "Immunosuppression adherence (never stop without contacting the team)"),
             ("home_monitoring", "Home monitoring: temperature, BP, weight, home spirometry (FEV1/FVC), action thresholds"),
             ("warning_signs", "Warning signs: fever >38C, SpO2 decline, spirometry drop >10%, sputum change, rash, neuro symptoms, oedema"),
             ("infection_prevention", "Infection prevention: hand hygiene, avoid crowds, sun, pets, food safety"),
             ("surgical_precautions", "Surgical precautions: lifting restrictions, wound care, 6-8 weeks"),
             ("sun_skin", "Sun protection & skin surveillance (SPF 50+, annual dermatology)"),
             ("drug_interactions", "Drug interactions: OTC, herbals, grapefruit with tacrolimus"),
             ("followup_schedule", "Follow-up: clinic within 7 days, bronchoscopy at 1 month")]
EPISODE_DISCHARGE = [
    ("discharge_gate", "Mandatory discharge criteria - ALL must be met (PERIOP-02 5.1)", [F(k, l, "check", wide=True) for k, l in DISCHARGE_GATE]),
    ("discharge_education", "Pre-discharge education checklist (PERIOP-02 5.2)", [F(k, l, "check", wide=True) for k, l in EDUCATION]),
    ("discharge_summary", "Discharge summary", [
        F("icu_days", "ICU days", "number"), F("ventilator_days", "Ventilator days", "number"), F("extubation_at", "Extubated at", "datetime"),
        F("complications", "Complications during admission", "textarea", wide=True), F("discharge_meds", "Discharge medications", "textarea", wide=True),
        F("first_clinic_date", "First clinic date", "date"), F("bronch_date", "1-month bronchoscopy date", "date"),
    ]),
]

# ---------------------------------------------------------------- follow-up visit (months 1,3,6,9,12 + annual)
VISIT_TYPES = [("month1", "Month 1"), ("month3", "Month 3"), ("month6", "Month 6"), ("month9", "Month 9"), ("month12", "Month 12"),
               ("annual", "Annual (after year 1)"), ("unscheduled", "Unscheduled / acute")]
FOLLOWUP_FORM = [
    ("vitals", "Clinical", [
        F("weight_kg", "Weight (kg)", "number", step="0.1"), F("bp", "BP"), F("temp", "Temperature (C)", "number", step="0.1"),
        F("spo2", "SpO2 (%)", "number"), F("symptoms", "Symptoms / interval history", "textarea", wide=True),
        F("home_spiro_baseline", "Home spirometry personal-best FEV1 (L)", "number", step="0.01"),
        F("home_spiro_latest", "Home spirometry latest FEV1 (L)", "number", step="0.01"),
    ]),
    ("labs", "Laboratory", [
        F("egfr", "eGFR", "number"), F("wbc", "WBC", "number", step="0.1"), F("hb", "Hb", "number", step="0.1"), F("platelets", "Platelets", "number"),
        F("lfts", "LFTs"), F("mg", "Mg", "number", step="0.01"), F("glucose_hba1c", "Glucose / HbA1c"),
        F("cmv_pcr", "CMV PCR"), F("other_labs", "Other", "textarea", wide=True),
    ]),
    ("immuno", "Immunosuppression & medications", [
        F("tacrolimus_dose", "Tacrolimus dose"), F("mmf_dose", "MMF dose"), F("steroid_dose", "Prednisolone dose"),
        F("cmv_prophylaxis", "CMV prophylaxis (agent / stop date)"), F("pcp_prophylaxis", "PCP prophylaxis"), F("other_meds", "Other medications", "textarea", wide=True),
        F("adherence", "Adherence concerns", "select", [("none", "None"), ("some", "Some"), ("major", "Major")]),
    ]),
    ("graft", "Allograft surveillance", [
        F("bronch_done", "Bronchoscopy done this visit?", "yesno"),
        F("tbbx_a", "Acute cellular rejection grade A", "select", [("A0", "A0"), ("A1", "A1"), ("A2", "A2"), ("A3", "A3"), ("A4", "A4")]),
        F("tbbx_b", "Lymphocytic bronchiolitis grade B", "select", [("B0", "B0"), ("B1R", "B1R"), ("B2R", "B2R")]),
        F("amr", "Antibody-mediated rejection", "select", [("none", "None"), ("possible", "Possible"), ("probable", "Probable"), ("definite", "Definite")]),
        F("dsa", "DSA", "select", [("neg", "Negative"), ("pos", "Positive"), ("na", "Not done")]), F("dsa_detail", "DSA detail (MFI / specificity)"),
        F("ddcfdna", "dd-cfDNA (% or copies/mL)"), F("bal_culture", "BAL culture / microbiology", "textarea", wide=True),
        F("clad", "CLAD stage", "select", [("none", "No CLAD"), ("bos0p", "BOS 0p (potential)"), ("bos1", "BOS 1"), ("bos2", "BOS 2"), ("bos3", "BOS 3"), ("ras", "RAS / mixed")]),
        F("imaging", "HRCT / CXR findings", "textarea", wide=True),
    ]),
    ("complications", "Complications & surveillance", [
        F("infection", "Infection this interval", "textarea", wide=True), F("renal", "Renal impairment (CNI)"), F("diabetes", "Post-transplant diabetes"),
        F("skin", "Skin check / dermatology"), F("malignancy", "Malignancy / PTLD concern"), F("bone", "Bone health"), F("psych", "Psychological / adherence support"),
        F("readmission", "Readmission since last visit?", "yesno"),
    ]),
    ("plan", "Assessment & plan", [F("assessment", "Assessment", "textarea", wide=True), F("plan", "Plan / changes", "textarea", wide=True),
                                     F("rehab", "Rehabilitation status"), F("mdt_review", "Needs MDT post-transplant review?", "yesno")]),
]

# ---------------------------------------------------------------- rules
BRONCH_SCHEDULE = [("Day 0/1", "Bedside routine", "Inspect anastomoses, clear secretions, confirm patency"),
                   ("Day 1-3 (if concern)", "Therapeutic / diagnostic", "Atelectasis, mucus plugging, infiltrate, culture"),
                   ("1 month", "TBBx + BAL (scheduled)", "Protocol surveillance; rejection grading; culture")]
CMV_PROTOCOL = {
    ("pos", "neg"): "D+/R-  HIGHEST risk: valganciclovir 900 mg daily (or IV ganciclovir 5 mg/kg per renal function) for minimum 6 months; CMV PCR weekly x4 then monthly.",
    ("pos", "pos"): "D+/R+  HIGH risk: valganciclovir 900 mg daily for minimum 3 months; CMV PCR monthly.",
    ("neg", "pos"): "D-/R+  INTERMEDIATE risk: valganciclovir 900 mg daily for minimum 3 months.",
    ("neg", "neg"): "D-/R-  LOW risk: acyclovir prophylaxis; CMV PCR only if symptomatic.",
}


def cmv_advice(donor, recipient):
    return CMV_PROTOCOL.get(((donor or "").lower()[:3], (recipient or "").lower()[:3]))


def months_since(tx_date, on):
    if not tx_date or not on:
        return None
    return (on.year - tx_date.year) * 12 + (on.month - tx_date.month) - (1 if on.day < tx_date.day else 0)


def tac_target(months):
    """CDH-LTU-PERIOP-02 4.5: months 1-3 = 10-15 ng/mL; months 4-12 = 8-12 ng/mL (none stated afterwards)."""
    if months is None:
        return None
    if months < 3:
        return (10.0, 15.0)
    if months < 12:
        return (8.0, 12.0)
    return None


def pgd_grade(pf, infiltrates, on_ecmo=False):
    """ISHLT PGD grade from PaO2/FiO2 + radiographic infiltrates (PERIOP-02 3.2). ECMO = grade 3."""
    if on_ecmo:
        return 3
    if not infiltrates or pf is None:
        return 0
    if pf >= 300:
        return 0
    if pf >= 200:
        return 1
    if pf >= 100:
        return 2
    return 3


PGD_MANAGEMENT = {
    0: "Standard lung-protective ventilation. Routine monitoring. Early extubation as planned.",
    1: "Continue protective ventilation. Review fluid balance. ABG q2h. Diuresis.",
    2: "Increase PEEP 8-12 cmH2O; Pplat <30; prone positioning if refractory. Consider ECMO consultation.",
    3: "VV- or VA-ECMO per protocol. TV 4-6 mL/kg IBW; PEEP 8-12; Pplat <30; minimise FiO2. iNO may be added.",
}


def fev1_drop_pct(baseline, latest):
    if baseline and latest and baseline > 0:
        return round((baseline - latest) / baseline * 100, 1)
    return None


def completion(fields, values):
    """(done, total) for check-type fields in a section."""
    checks = [f["name"] for f in fields if f["type"] == "check"]
    return sum(1 for n in checks if values.get(n)), len(checks)
