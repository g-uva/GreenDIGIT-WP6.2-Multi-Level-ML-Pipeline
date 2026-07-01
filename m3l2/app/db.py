from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.types import JSON

from m3l2.app.config import get_settings


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class ExecutionRecord(Base):
    __tablename__ = "execution_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exec_unit_id: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    site_id: Mapped[str] = mapped_column(String, index=True, nullable=False)
    ri_type: Mapped[str] = mapped_column(String, default="unknown")
    start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    stop_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)
    energy_wh: Mapped[float | None] = mapped_column(Float, nullable=True)
    work: Mapped[float | None] = mapped_column(Float, nullable=True)
    work_type: Mapped[str] = mapped_column(String, default="unknown")
    owner: Mapped[str | None] = mapped_column(String, nullable=True)
    raw_json: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ModelRegistry(Base):
    __tablename__ = "model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    model_name: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String)
    version: Mapped[str] = mapped_column(String, unique=True)
    path: Mapped[str] = mapped_column(String)
    trained_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    training_window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    training_window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    metrics: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    feature_schema: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)


class ForecastCache(Base):
    __tablename__ = "forecast_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    site_id: Mapped[str | None] = mapped_column(String, index=True)
    target: Mapped[str] = mapped_column(String)
    horizon: Mapped[str] = mapped_column(String)
    step: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    valid_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    model_version: Mapped[str] = mapped_column(String)
    predictions: Mapped[list[dict[str, Any]]] = mapped_column(JSON)
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)


def _normalise_database_url(url: str) -> str:
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def _engine_kwargs(url: str) -> dict[str, Any]:
    if url.startswith("sqlite"):
        return {"connect_args": {"check_same_thread": False}}
    return {}


_engine: Engine | None = None
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        url = _normalise_database_url(get_settings().database_url)
        _engine = create_engine(url, future=True, **_engine_kwargs(url))
        SessionLocal.configure(bind=_engine)
    return _engine


def configure_database(database_url: str) -> Engine:
    global _engine
    url = _normalise_database_url(database_url)
    if _engine is not None:
        _engine.dispose()
    _engine = create_engine(url, future=True, **_engine_kwargs(url))
    SessionLocal.configure(bind=_engine)
    return _engine


def create_tables() -> None:
    Base.metadata.create_all(bind=get_engine())


def db_status() -> str:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return "ok"
    except Exception:
        return "error"
