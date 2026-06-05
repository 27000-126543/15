from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool, StaticPool
from config import settings, BASE_DIR
import threading
from loguru import logger
import sys
import os
from config import LOG_DIR
from typing import Generator

if os.environ.get("WORKER_MODE") != "1":
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
        level="INFO",
    )
    logger.add(
        f"{LOG_DIR}/live_ops_{{time:YYYY-MM-DD}}.log",
        rotation="00:00",
        retention="30 days",
        compression="zip",
        level="DEBUG",
        encoding="utf-8",
    )

_db_url = settings.get_effective_db_url()
_is_sqlite = "sqlite" in _db_url

_engine_kwargs = {
    "pool_pre_ping": True,
    "echo": settings.DB_ECHO,
}

if _is_sqlite:
    _engine_kwargs["connect_args"] = {"check_same_thread": False}
    _engine_kwargs["poolclass"] = StaticPool
    logger.info(f"使用 SQLite 数据库: {_db_url}")
else:
    _engine_kwargs.update({
        "poolclass": QueuePool,
        "pool_size": settings.DB_POOL_SIZE,
        "max_overflow": settings.DB_MAX_OVERFLOW,
        "pool_recycle": settings.DB_POOL_RECYCLE,
        "pool_timeout": 30,
    })
    logger.info(
        f"使用 PostgreSQL 数据库: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}/{settings.POSTGRES_DB} "
        f"(连接池: {settings.DB_POOL_SIZE}/{settings.DB_MAX_OVERFLOW})"
    )

engine = create_engine(_db_url, **_engine_kwargs)

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)

Base = declarative_base()

_db_lock = threading.Lock()


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_db_session():
    with _db_lock:
        return SessionLocal()


def test_db_connection() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.warning(f"数据库连接测试: ✗ 失败 - {e}")
        return False
