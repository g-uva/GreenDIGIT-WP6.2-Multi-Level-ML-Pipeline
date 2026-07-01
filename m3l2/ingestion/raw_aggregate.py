from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from m3l2.app.db import ExecutionRecord, SessionLocal, SiteProfile, SiteStatusSnapshot, create_tables, utc_now


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


def aggregate_row_to_site_status(row: dict[str, Any], source: str, compute_capacity: float | None) -> dict[str, Any]:
    timestamp = _parse_bucket(row["bucket_15m"])
    ncores = _float_or_none(row.get("ncores")) or 0.0
    records = _float_or_none(row.get("records")) or 0.0
    energy_wh = _float_or_none(row.get("energy_wh"))
    work = _float_or_none(row.get("work")) or 0.0
    cpu_util = None
    if compute_capacity and compute_capacity > 0:
        cpu_util = max(0.0, min(100.0, 100.0 * ncores / compute_capacity))
    return {
        "site_id": row.get("site_id") or "unknown-site",
        "ri_type": _ri_type(row.get("activity")),
        "timestamp": timestamp,
        "operational_status": "UP",
        "maintenance_flag": False,
        "node_availability": 1.0,
        "link_availability": 1.0,
        "stability_score": 1.0,
        "cpu_util_avg": cpu_util,
        "free_cpu_capacity": max(float(compute_capacity or ncores) - ncores, 0.0),
        "queue_length": 0,
        "remaining_jobs": int(records),
        "provisioning_delay_s": 0.0,
        "load_index": (cpu_util or 0.0) / 100.0,
        "energy_consumed": energy_wh,
        "energy_per_task_proxy": None if not records else energy_wh / records if energy_wh is not None else None,
        "data_confidence": 0.7,
        "coverage_ratio": 1.0,
        "stale_flag": False,
        "raw_json": {**row, "source_file": source, "source_schema": "summary_sites_15m", "work_observed": work},
    }


def _upsert_profile(session, site_id: str, ri_type: str, compute_capacity: float | None, source: str) -> None:
    existing = session.execute(select(SiteProfile).where(SiteProfile.site_id == site_id)).scalar_one_or_none()
    payload = {
        "site_id": site_id,
        "ri_type": ri_type,
        "compute_capacity": compute_capacity,
        "gpu_capacity": None,
        "storage_capacity": None,
        "network_topology": "unknown",
        "supported_workload_types": sorted({ri_type, "batch", "ml"}),
        "energy_capabilities": {"metering": "aggregate_validation", "source": source},
        "raw_json": {"source_file": source, "source_schema": "summary_sites_15m"},
        "updated_at": utc_now(),
    }
    if existing is None:
        session.add(SiteProfile(**payload))
        return
    for key, value in payload.items():
        setattr(existing, key, value)


def load_summary_sites_15m(csv_path: str | Path, source: str | None = None) -> dict[str, Any]:
    create_tables()
    path = Path(csv_path)
    source_name = source or str(path)
    required = {"bucket_15m", "site_id", "records", "energy_wh", "work"}
    summary = {
        "source": source_name,
        "rows": 0,
        "inserted": 0,
        "updated": 0,
        "status_inserted": 0,
        "profiles_upserted": 0,
        "skipped": 0,
    }

    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        return summary
    missing = required - set(rows[0].keys())
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
    capacities: dict[str, float] = {}
    ri_types: dict[str, str] = {}
    for row in rows:
        site_id = row.get("site_id") or "unknown-site"
        capacities[site_id] = max(capacities.get(site_id, 0.0), _float_or_none(row.get("ncores")) or 0.0)
        ri_types[site_id] = _ri_type(row.get("activity"))

    with SessionLocal() as session:
        for site_id, capacity in capacities.items():
            _upsert_profile(session, site_id, ri_types.get(site_id, "unknown"), capacity, source_name)
            summary["profiles_upserted"] += 1

        for row in rows:
            summary["rows"] += 1
            try:
                record = aggregate_row_to_execution_record(row, source_name)
                status = aggregate_row_to_site_status(row, source_name, capacities.get(record["site_id"]))
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
            existing_status = None
            for candidate in session.execute(
                select(SiteStatusSnapshot).where(
                    SiteStatusSnapshot.site_id == status["site_id"],
                    SiteStatusSnapshot.timestamp == status["timestamp"],
                )
            ).scalars():
                if (candidate.raw_json or {}).get("source_file") == source_name:
                    existing_status = candidate
                    break
            if existing_status is None:
                session.add(SiteStatusSnapshot(**status, ingested_at=utc_now()))
                summary["status_inserted"] += 1
            else:
                for key, value in status.items():
                    setattr(existing_status, key, value)
                existing_status.ingested_at = utc_now()
        session.commit()
    return summary
