import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import List, Optional


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
EXPORT_DIR = BASE_DIR / "exports"
CHART_DIR = EXPORT_DIR / "charts"

for d in [DATA_DIR, LOG_DIR, EXPORT_DIR, CHART_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class Settings(BaseSettings):
    APP_NAME: str = "企业级直播运营智能决策系统"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str = "live-ops-super-secret-key-2024"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    DATABASE_URL: str = f"sqlite:///{DATA_DIR}/live_ops.db"

    REDIS_URL: Optional[str] = None
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    PLATFORMS: List[str] = ["抖音", "快手", "淘宝直播", "视频号", "B站直播"]

    INDUSTRY_RETURN_RATE: float = 0.08
    SELL_OUT_THRESHOLD: float = 0.80
    RETURN_RATE_ALERT_MULTIPLIER: float = 1.20
    RETURN_RATE_ALERT_DAYS: int = 3
    PROMO_APPROVAL_THRESHOLD: float = 500000.0

    DAILY_REPORT_HOUR: int = 2
    DAILY_REPORT_MINUTE: int = 30

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
