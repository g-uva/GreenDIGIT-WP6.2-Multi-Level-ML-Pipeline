from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from m3l2.app.config import get_settings
from m3l2.app.db import ExecutionRecord, SessionLocal, create_tables, utc_now
from m3l2.ingestion.metricsdb_client import MetricsDBClient
from m3l2.ingestion.normalise import normalise_execution_record

logger = logging.getLogger(__name__)


def _ensure_utc(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.replace("Z", "+00:00")
        value = datetime.fromisoformat(text)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _upsert_record(session: Session, record: dict[str, Any]) -> str:
    existing = session.execute(
        select(ExecutionRecord).where(ExecutionRecord.exec_unit_id == record["exec_unit_id"])
    ).scalar_one_or_none()
    if existing is None:
        session.add(ExecutionRecord(**record, ingested_at=utc_now()))
        return "inserted"
    for key, value in record.items():
        setattr(existing, key, value)
    existing.ingested_at = utc_now()
    return "updated"


def run_ingestion(
    start_ts: datetime | str | None = None,
    end_ts: datetime | str | None = None,
    sites: list[str] | None = None,
) -> dict[str, Any]:
    create_tables()
    settings = get_settings()
    end = _ensure_utc(end_ts) or utc_now()
    start = _ensure_utc(start_ts) or end - timedelta(hours=settings.batch_lookback_hours)

    raw_records = MetricsDBClient().fetch_execution_records(start, end, sites)
    summary = {
        "fetched": len(raw_records),
        "normalised": 0,
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "start_ts": start.isoformat(),
        "end_ts": end.isoformat(),
    }

    with SessionLocal() as session:
        for raw in raw_records:
            try:
                record = normalise_execution_record(raw)
            except ValueError as exc:
                summary["skipped"] += 1
                logger.warning("Skipping execution record: %s", exc)
                continue
            action = _upsert_record(session, record)
            summary["normalised"] += 1
            summary[action] += 1
        session.commit()

    logger.info("Ingestion completed: %s", summary)
    return summary

