import os
from pathlib import Path
from pydantic_settings import BaseSettings
from typing import List, Optional, Dict, Any


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
EXPORT_DIR = BASE_DIR / "exports"
CHART_DIR = EXPORT_DIR / "charts"
WORKER_DIR = BASE_DIR / "workers"

for d in [DATA_DIR, LOG_DIR, EXPORT_DIR, CHART_DIR, WORKER_DIR]:
    d.mkdir(parents=True, exist_ok=True)


class PlatformAPIConfig(BaseSettings):
    enabled: bool = False
    base_url: str = ""
    api_token: str = ""
    timeout: int = 30
    retry_count: int = 3
    retry_delay: float = 1.0

    class Config:
        extra = "allow"


class Settings(BaseSettings):
    APP_NAME: str = "企业级直播运营智能决策系统"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"
    SECRET_KEY: str = "live-ops-super-secret-key-2024"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7

    DB_ENGINE: str = os.environ.get("DB_ENGINE", "sqlite")
    DATABASE_URL: str = f"sqlite:///{DATA_DIR}/live_ops.db"
    POSTGRES_HOST: str = os.environ.get("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.environ.get("POSTGRES_PORT", "5432"))
    POSTGRES_USER: str = os.environ.get("POSTGRES_USER", "live_ops")
    POSTGRES_PASSWORD: str = os.environ.get("POSTGRES_PASSWORD", "live_ops")
    POSTGRES_DB: str = os.environ.get("POSTGRES_DB", "live_ops")

    DB_POOL_SIZE: int = int(os.environ.get("DB_POOL_SIZE", "20"))
    DB_MAX_OVERFLOW: int = int(os.environ.get("DB_MAX_OVERFLOW", "50"))
    DB_POOL_RECYCLE: int = int(os.environ.get("DB_POOL_RECYCLE", "3600"))
    DB_ECHO: bool = False

    REDIS_ENABLED: bool = os.environ.get("REDIS_ENABLED", "false").lower() == "true"
    REDIS_URL: str = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    REDIS_HOST: str = os.environ.get("REDIS_HOST", "localhost")
    REDIS_PORT: int = int(os.environ.get("REDIS_PORT", "6379"))
    REDIS_DB: int = int(os.environ.get("REDIS_DB", "0"))
    REDIS_PASSWORD: Optional[str] = os.environ.get("REDIS_PASSWORD")
    REDIS_CACHE_TTL: int = int(os.environ.get("REDIS_CACHE_TTL", "300"))
    REDIS_REALTIME_TTL: int = int(os.environ.get("REDIS_REALTIME_TTL", "60"))

    CELERY_ENABLED: bool = False
    CELERY_BROKER_URL: Optional[str] = None
    CELERY_RESULT_BACKEND: Optional[str] = None

    PLATFORMS: List[str] = ["抖音", "快手", "淘宝直播", "视频号", "B站直播"]

    DOUYIN_API_ENABLED: bool = os.environ.get("DOUYIN_API_ENABLED", "false").lower() == "true"
    DOUYIN_API_BASE_URL: str = os.environ.get("DOUYIN_API_BASE_URL", "https://open.douyin.com")
    DOUYIN_API_TOKEN: str = os.environ.get("DOUYIN_API_TOKEN", "")
    DOUYIN_API_TIMEOUT: int = 30

    KUAISHOU_API_ENABLED: bool = os.environ.get("KUAISHOU_API_ENABLED", "false").lower() == "true"
    KUAISHOU_API_BASE_URL: str = os.environ.get("KUAISHOU_API_BASE_URL", "https://open.kuaishou.com")
    KUAISHOU_API_TOKEN: str = os.environ.get("KUAISHOU_API_TOKEN", "")
    KUAISHOU_API_TIMEOUT: int = 30

    TAOBAO_API_ENABLED: bool = os.environ.get("TAOBAO_API_ENABLED", "false").lower() == "true"
    TAOBAO_API_BASE_URL: str = os.environ.get("TAOBAO_API_BASE_URL", "https://eco.taobao.com")
    TAOBAO_API_TOKEN: str = os.environ.get("TAOBAO_API_TOKEN", "")
    TAOBAO_API_TIMEOUT: int = 30

    WECHAT_API_ENABLED: bool = os.environ.get("WECHAT_API_ENABLED", "false").lower() == "true"
    WECHAT_API_BASE_URL: str = os.environ.get("WECHAT_API_BASE_URL", "https://api.weixin.qq.com")
    WECHAT_API_TOKEN: str = os.environ.get("WECHAT_API_TOKEN", "")
    WECHAT_API_TIMEOUT: int = 30

    BILIBILI_API_ENABLED: bool = os.environ.get("BILIBILI_API_ENABLED", "false").lower() == "true"
    BILIBILI_API_BASE_URL: str = os.environ.get("BILIBILI_API_BASE_URL", "https://api.live.bilibili.com")
    BILIBILI_API_TOKEN: str = os.environ.get("BILIBILI_API_TOKEN", "")
    BILIBILI_API_TIMEOUT: int = 30

    REPORT_WORKER_ISOLATED: bool = True
    REPORT_WORKER_TIMEOUT: int = 120
    REPORT_WORKER_PYTHON: Optional[str] = None

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

    def get_postgres_url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    def get_effective_db_url(self) -> str:
        if self.DB_ENGINE.lower() == "postgresql":
            return self.get_postgres_url()
        return self.DATABASE_URL

    def get_platform_config(self, platform_name: str) -> PlatformAPIConfig:
        mapping = {
            "抖音": {
                "enabled": self.DOUYIN_API_ENABLED,
                "base_url": self.DOUYIN_API_BASE_URL,
                "api_token": self.DOUYIN_API_TOKEN,
                "timeout": self.DOUYIN_API_TIMEOUT,
            },
            "快手": {
                "enabled": self.KUAISHOU_API_ENABLED,
                "base_url": self.KUAISHOU_API_BASE_URL,
                "api_token": self.KUAISHOU_API_TOKEN,
                "timeout": self.KUAISHOU_API_TIMEOUT,
            },
            "淘宝直播": {
                "enabled": self.TAOBAO_API_ENABLED,
                "base_url": self.TAOBAO_API_BASE_URL,
                "api_token": self.TAOBAO_API_TOKEN,
                "timeout": self.TAOBAO_API_TIMEOUT,
            },
            "视频号": {
                "enabled": self.WECHAT_API_ENABLED,
                "base_url": self.WECHAT_API_BASE_URL,
                "api_token": self.WECHAT_API_TOKEN,
                "timeout": self.WECHAT_API_TIMEOUT,
            },
            "B站直播": {
                "enabled": self.BILIBILI_API_ENABLED,
                "base_url": self.BILIBILI_API_BASE_URL,
                "api_token": self.BILIBILI_API_TOKEN,
                "timeout": self.BILIBILI_API_TIMEOUT,
            },
        }
        cfg = mapping.get(platform_name, {})
        return PlatformAPIConfig(**cfg)


settings = Settings()
