from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from m3l2.app.db import ExecutionRecord, SessionLocal, create_tables, utc_now


def _parse_bucket(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _exec_unit_id(source: str, row: dict[str, Any]) -> str:
    key = json.dumps(
        {
            "source": source,
            "bucket_15m": row.get("bucket_15m"),
            "site_id": row.get("site_id"),
            "vo": row.get("vo"),
            "activity": row.get("activity"),
        },
        sort_keys=True,
    )
    return f"aggregate-{hashlib.sha256(key.encode('utf-8')).hexdigest()[:32]}"


def _ri_type(activity: str | None) -> str:
    value = (activity or "").strip().lower()
    return value if value in {"cloud", "iot", "network", "grid"} else "unknown"


def aggregate_row_to_execution_record(row: dict[str, Any], source: str) -> dict[str, Any]:
    start_ts = _parse_bucket(row["bucket_15m"])
    return {
        "exec_unit_id": _exec_unit_id(source, row),
        "site_id": row.get("site_id") or "unknown-site",
        "ri_type": _ri_type(row.get("activity")),
        "start_ts": start_ts,
        "stop_ts": start_ts + timedelta(minutes=15),
        "status": "aggregated",
        "energy_wh": _float_or_none(row.get("energy_wh")),
        "work": _float_or_none(row.get("work")),
        "work_type": "cpu_time" if row.get("work") not in (None, "") else "unknown",
        "owner": row.get("vo") or None,
        "raw_json": {**row, "source_file": source, "source_schema": "summary_sites_15m"},
    }


def load_summary_sites_15m(csv_path: str | Path, source: str | None = None) -> dict[str, Any]:
    create_tables()
    path = Path(csv_path)
    source_name = source or str(path)
    required = {"bucket_15m", "site_id", "records", "energy_wh", "work"}
    summary = {"source": source_name, "rows": 0, "inserted": 0, "updated": 0, "skipped": 0}

    with path.open(newline="") as handle, SessionLocal() as session:
        reader = csv.DictReader(handle)
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} is missing required columns: {sorted(missing)}")

        for row in reader:
            summary["rows"] += 1
            try:
                record = aggregate_row_to_execution_record(row, source_name)
            except Exception:
                summary["skipped"] += 1
                continue

            existing = session.execute(
                select(ExecutionRecord).where(ExecutionRecord.exec_unit_id == record["exec_unit_id"])
            ).scalar_one_or_none()
            if existing is None:
                session.add(ExecutionRecord(**record, ingested_at=utc_now()))
                summary["inserted"] += 1
            else:
                for key, value in record.items():
                    setattr(existing, key, value)
                existing.ingested_at = utc_now()
                summary["updated"] += 1
        session.commit()
    return summary

