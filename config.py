import os
from datetime import timedelta
from dotenv import load_dotenv

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))


def _db_url():
    url = os.environ.get("DATABASE_URL", "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url or "sqlite:///" + os.path.join(BASE_DIR, "instance", "ltu.db")


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    SQLALCHEMY_DATABASE_URI = _db_url()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "false").lower() == "true"
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)
    SESSION_IDLE_MINUTES = float(os.environ.get("SESSION_IDLE_MINUTES", "15"))
    MAIN_APP_URL = os.environ.get("MAIN_APP_URL", "").rstrip("/")
    MAIN_APP_LTU_KEY = os.environ.get("MAIN_APP_LTU_KEY", "")
    LTU_ADMIN_EMAIL = os.environ.get("LTU_ADMIN_EMAIL", "admin@example.com")
    LTU_ADMIN_PASSWORD = os.environ.get("LTU_ADMIN_PASSWORD", "")
