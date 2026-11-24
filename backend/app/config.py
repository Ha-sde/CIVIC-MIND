"""Central configuration. Every value can be overridden with an environment variable."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


DEFAULT_WEIGHTS = {
    "reports": 0.30,        # how many citizens reported the same issue
    "severity": 0.30,       # AI estimated severity (1-5)
    "category": 0.15,       # inherent importance of the category
    "age": 0.15,            # time unresolved (saturates at 14 days)
    "vulnerability": 0.10,  # near school / hospital / transit (public infrastructure only)
}


def _weights():
    raw = os.getenv("PRIORITY_WEIGHTS")
    if not raw:
        return dict(DEFAULT_WEIGHTS)
    try:
        merged = {**DEFAULT_WEIGHTS, **{k: float(v) for k, v in json.loads(raw).items() if k in DEFAULT_WEIGHTS}}
        return merged
    except Exception:
        return dict(DEFAULT_WEIGHTS)


class Settings:
    APP_NAME = "Civic Mind"
    ROOT = ROOT
    FRONTEND_DIR = ROOT / "frontend"
    DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data")))
    UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", str(Path(os.getenv("DATA_DIR", str(ROOT / "data"))) / "uploads")))
    DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{Path(os.getenv('DATA_DIR', str(ROOT / 'data'))) / 'civicmind.db'}")

    SECRET_KEY = os.getenv("SECRET_KEY", "dev-only-secret-change-me-before-deploying-0123456789")
    ACCESS_TOKEN_HOURS = int(os.getenv("ACCESS_TOKEN_HOURS", "24"))
    CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

    # OTP: "demo" accepts the fixed DEMO_OTP for everyone, "log" generates a random code and prints it to the server log.
    OTP_MODE = os.getenv("OTP_MODE", "demo").lower()
    DEMO_OTP = os.getenv("DEMO_OTP", "123456")
    OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))
    OFFICIAL_INVITE_CODE = os.getenv("OFFICIAL_INVITE_CODE", "")  # empty = not required

    # AI engine
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
    AI_TIMEOUT = float(os.getenv("AI_TIMEOUT", "25"))

    # Clustering / SLA
    CLUSTER_RADIUS_M = float(os.getenv("CLUSTER_RADIUS_M", "150"))
    CLUSTER_WINDOW_DAYS = int(os.getenv("CLUSTER_WINDOW_DAYS", "30"))
    ACK_SLA_HOURS = int(os.getenv("ACK_SLA_HOURS", "48"))
    REOPEN_WINDOW_DAYS = int(os.getenv("REOPEN_WINDOW_DAYS", "7"))
    WEIGHTS = _weights()

    # Uploads
    MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "15"))
    MAX_FILES = int(os.getenv("MAX_FILES", "5"))

    SEED_DEMO = _bool(os.getenv("SEED_DEMO"), True)
    MAP_DEFAULT = os.getenv("MAP_DEFAULT", "16.7050,74.2433")


settings = Settings()
