# CDH Lung Transplant Unit (LTU) app

Standalone Flask app: referral intake -> weekly MDT decision (CDH-LTU-MDT-05) -> candidate registry/waitlist ->
transplant episode (offer, pre-op, intra-op, CTICU, PGD grading, tacrolimus troughs, discharge gate) ->
post-transplant follow-up (months 1/3/6/9/12, annual, boarded patients) -> protocol library.

## Run locally
    pip install -r requirements.txt
    LTU_ADMIN_PASSWORD='ChangeMe#123' LTU_ADMIN_EMAIL=you@example.org python -c "from app import create_app; create_app().run(debug=True)"
    python test_ltu.py

## Deploy (Render)
1. New private git repo containing this folder; new Render Web Service + PostgreSQL.
2. Start command: `gunicorn "app:create_app()"` (Procfile).
3. Environment: `SECRET_KEY`, `DATABASE_URL`, `SESSION_COOKIE_SECURE=1`, `LTU_ADMIN_EMAIL`, `LTU_ADMIN_PASSWORD` (first admin, created once),
   `MAIN_APP_URL` (main app base URL) and `MAIN_APP_LTU_KEY` (same value as `LTU_LOOKUP_KEY` on the main app).
4. On the main app set `LTU_LOOKUP_KEY` and deploy `ltu_api.py` (read-only demographics by Civil ID).

## Roles
Admin / Medical Director / Surgical Director can finalise MDT decisions and change candidate status. Coordinator and Medical Director approve accounts.
Referring physicians self-register (pending until approved), see only their own referrals, and see the MDT decision only after the team marks it as sent.

## Notes
- Follow-up forms (Year-1 / Annual) are designed from the content the protocols reference; the original form files were not supplied - review them.
- Auto-logout after 15 min idle (configurable `SESSION_IDLE_MINUTES`). All views of patient data are audit-logged.
