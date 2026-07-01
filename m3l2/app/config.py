from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./m3l2.db")
    cnr_host: str = os.getenv("CNR_HOST", "")
    cnr_user: str = os.getenv("CNR_USER", "")
    cnr_password: str = os.getenv("CNR_POSTEGRESQL_PASSWORD", "")
    cnr_database: str = os.getenv("CNR_GD_DB", "greendigit-db")
    cnr_port: int = int(os.getenv("CNR_PORT", "5432"))
    batch_lookback_hours: int = int(os.getenv("M3L2_BATCH_LOOKBACK_HOURS", "24"))
    train_interval_hours: int = int(os.getenv("M3L2_TRAIN_INTERVAL_HOURS", "6"))
    forecast_horizon_hours: int = int(os.getenv("M3L2_FORECAST_HORIZON_HOURS", "24"))
    forecast_step_minutes: int = int(os.getenv("M3L2_FORECAST_STEP_MINUTES", "60"))
    model_dir: Path = Path(os.getenv("M3L2_MODEL_DIR", "./artifacts/models"))
    min_training_records: int = int(os.getenv("M3L2_MIN_TRAINING_RECORDS", "20"))
    enable_scheduler: bool = _bool_env("M3L2_ENABLE_SCHEDULER", True)
    jwt_secret: str = os.getenv("JWT_SECRET", "")
    jwt_token_ttl_hours: int = int(os.getenv("JWT_TOKEN_TTL_HOURS", "24"))
    allowed_emails_path: str = os.getenv("ALLOWED_EMAILS_PATH", "allowed_emails.txt")
    site_adapter_allowed_email_domains: str = os.getenv("SITE_ADAPTER_ALLOWED_EMAIL_DOMAINS", "uva.nl,uth.gr")
    egi_checkin_issuer: str = os.getenv("EGI_CHECKIN_ISSUER", "")
    egi_checkin_audience: str = os.getenv("EGI_CHECKIN_AUDIENCE", "")

    @property
    def cnr_database_url(self) -> str | None:
        if not self.cnr_host or not self.cnr_user or not self.cnr_password:
            return None
        return (
            f"postgresql+psycopg://{self.cnr_user}:{self.cnr_password}"
            f"@{self.cnr_host}:{self.cnr_port}/{self.cnr_database}"
        )

    @property
    def allowed_site_adapter_email_domains(self) -> set[str]:
        return {domain.strip().lower() for domain in self.site_adapter_allowed_email_domains.split(",") if domain.strip()}


def get_settings() -> Settings:
    return Settings()
