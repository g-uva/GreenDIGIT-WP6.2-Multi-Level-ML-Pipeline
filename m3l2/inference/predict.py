from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import joblib
import pandas as pd
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from m3l2.app.db import ExecutionRecord, SessionLocal, SiteProfile, SiteStatusSnapshot, create_tables, utc_now
from m3l2.app.schemas import PredictRequest
from m3l2.inference.cache import get_valid_cache, store_cache
from m3l2.training.registry import get_active_model
from m3l2.training.train import FEATURE_COLUMNS, TARGET

logger = logging.getLogger(__name__)


def _model_dump(request: PredictRequest | dict[str, Any]) -> dict[str, Any]:
    if isinstance(request, dict):
        return request
    if hasattr(request, "model_dump"):
        return request.model_dump()
    return request.dict()


def _parse_duration(value: str) -> timedelta:
    match = re.fullmatch(r"(\d+)([hm])", value.strip().lower())
    if not match:
        raise ValueError(f"Unsupported duration: {value}")
    amount = int(match.group(1))
    return timedelta(hours=amount) if match.group(2) == "h" else timedelta(minutes=amount)


def _quality(freshness: str, coverage: float, metrics: dict[str, Any] | None) -> dict[str, Any]:
    n_train = (metrics or {}).get("n_train") or 0
    if n_train >= 100 and coverage >= 0.9:
        confidence = "high"
    elif n_train >= 20 and coverage >= 0.5:
        confidence = "medium"
    else:
        confidence = "low"
    return {"freshness": freshness, "coverage": coverage, "confidence": confidence}


def _latest_context(session: Session, site_id: str) -> ExecutionRecord | None:
    return session.execute(
        select(ExecutionRecord)
        .where(ExecutionRecord.site_id == site_id)
        .order_by(desc(ExecutionRecord.start_ts))
    ).scalars().first()


def _latest_site_status(session: Session, site_id: str) -> SiteStatusSnapshot | None:
    return session.execute(
        select(SiteStatusSnapshot)
        .where(SiteStatusSnapshot.site_id == site_id)
        .order_by(desc(SiteStatusSnapshot.timestamp))
    ).scalars().first()


def _site_profile(session: Session, site_id: str) -> SiteProfile | None:
    return session.execute(select(SiteProfile).where(SiteProfile.site_id == site_id)).scalar_one_or_none()


def _site_ids(session: Session, requested: list[str] | None) -> list[str]:
    if requested:
        return requested
    return [
        site
        for site in session.execute(select(ExecutionRecord.site_id).distinct()).scalars().all()
        if site
    ]


def _duration_s(row: ExecutionRecord | None) -> float:
    if row and row.stop_ts and row.start_ts:
        return max(float((row.stop_ts - row.start_ts).total_seconds()), 0.0)
    return 0.0


def _base_feature_row(site_id: str, context: ExecutionRecord | None, ts: datetime, workload: dict[str, Any] | None) -> dict[str, Any]:
    workload = workload or {}
    work = workload.get("work", context.work if context else 0.0)
    feature_row = {
        "site_id": site_id,
        "ri_type": workload.get("ri_type", context.ri_type if context else "unknown"),
        "duration_s": float(workload.get("duration_s", _duration_s(context))),
        "work": float(work or 0.0),
        "hour": ts.hour,
        "day_of_week": ts.weekday(),
        "records_count_site_24h": float(workload.get("records_count_site_24h", 1.0 if context else 0.0)),
        "rolling_energy_mean_site_24h": float(
            workload.get("rolling_energy_mean_site_24h", context.energy_wh if context and context.energy_wh else 0.0)
        ),
        "rolling_work_mean_site_24h": float(
            workload.get("rolling_work_mean_site_24h", context.work if context and context.work else 0.0)
        ),
    }
    return feature_row


def _efficiency(context: ExecutionRecord | None, status: SiteStatusSnapshot | None, workload: dict[str, Any] | None, predicted_energy: float) -> dict[str, Any]:
    workload = workload or {}
    cpu_hours = workload.get("cpu_hours")
    gpu_hours = workload.get("gpu_hours")
    if cpu_hours is None and context and context.work:
        cpu_hours = float(context.work) / 3600.0
    energy_per_cpu_hour = None if not cpu_hours else predicted_energy / float(cpu_hours)
    energy_per_gpu_hour = None if not gpu_hours else predicted_energy / float(gpu_hours)
    carbon_g = None
    if status and status.carbon_intensity is not None:
        carbon_g = (predicted_energy / 1000.0) * status.carbon_intensity
    return {
        "energy_per_cpu_hour_wh": energy_per_cpu_hour,
        "energy_per_gpu_hour_wh": energy_per_gpu_hour,
        "workload_class": workload.get("class") or workload.get("workload_class"),
        "expected_workload_energy_wh": predicted_energy if workload else None,
        "expected_workload_carbon_g": carbon_g if workload else None,
    }


def _status_forecast(status: SiteStatusSnapshot | None, profile: SiteProfile | None, timestamps: list[datetime]) -> list[dict[str, Any]]:
    if status is None:
        return [
            {
                "ts": ts.isoformat(),
                "operational_status": "unknown",
                "availability": None,
                "free_cpu_capacity": profile.compute_capacity if profile else None,
                "free_gpu_capacity": profile.gpu_capacity if profile else None,
                "queue_length": None,
                "provisioning_delay_s": None,
                "maintenance_flag": False,
            }
            for ts in timestamps
        ]
    return [
        {
            "ts": ts.isoformat(),
            "operational_status": status.operational_status,
            "availability": status.node_availability,
            "free_cpu_capacity": status.free_cpu_capacity,
            "free_gpu_capacity": status.free_gpu_capacity,
            "queue_length": status.queue_length,
            "provisioning_delay_s": status.provisioning_delay_s,
            "maintenance_flag": status.maintenance_flag,
            "scheduled_maintenance": status.scheduled_maintenance,
            "load_index": status.load_index,
        }
        for ts in timestamps
    ]


def _predict_with_session(request: PredictRequest | dict[str, Any], session: Session) -> dict[str, Any]:
    payload = _model_dump(request)
    horizon = payload.get("horizon") or "24h"
    step = payload.get("step") or "1h"
    workload = payload.get("workload")
    use_cache = bool(payload.get("use_cache", True))
    horizon_delta = _parse_duration(horizon)
    step_delta = _parse_duration(step)
    if step_delta.total_seconds() <= 0 or horizon_delta.total_seconds() <= 0:
        raise ValueError("horizon and step must be positive")

    model_row = get_active_model(session, TARGET)
    if model_row is None:
        return {"status": "no_active_model", "detail": "No active energy_wh model is registered."}

    sites = _site_ids(session, payload.get("site_ids"))
    created_at = utc_now()
    valid_until = created_at + step_delta
    cached_predictions = []
    if use_cache:
        for site_id in sites:
            cached = get_valid_cache(session, site_id, TARGET, horizon, step)
            if cached is None or cached.model_version != model_row.version:
                cached_predictions = []
                break
            cached_predictions.append(
                {
                    "site_id": site_id,
                    "target": TARGET,
                    "forecast": cached.predictions,
                    "quality": {**(cached.quality or {}), "freshness": "cached"},
                }
            )
        if cached_predictions and len(cached_predictions) == len(sites):
            return {
                "created_at": created_at.isoformat(),
                "horizon": horizon,
                "step": step,
                "model_version": model_row.version,
                "predictions": cached_predictions,
            }

    model_bundle = joblib.load(model_row.path)
    pipeline = model_bundle["pipeline"] if isinstance(model_bundle, dict) else model_bundle
    n_steps = int(horizon_delta.total_seconds() // step_delta.total_seconds())
    predictions = []
    for site_id in sites:
        context = _latest_context(session, site_id)
        status = _latest_site_status(session, site_id)
        profile = _site_profile(session, site_id)
        forecast_rows = []
        feature_rows = []
        timestamps = []
        for idx in range(1, n_steps + 1):
            ts = created_at + (step_delta * idx)
            timestamps.append(ts)
            feature_rows.append(_base_feature_row(site_id, context, ts, workload))
        if feature_rows:
            frame = pd.DataFrame(feature_rows, columns=FEATURE_COLUMNS)
            values = pipeline.predict(frame)
        else:
            values = []
        for ts, value in zip(timestamps, values):
            forecast_rows.append({"ts": ts.isoformat(), "value": max(float(value), 0.0)})
        quality = _quality("fresh", 1.0 if context else 0.0, model_row.metrics)
        predicted_total = float(sum(point["value"] for point in forecast_rows))
        store_cache(session, site_id, TARGET, horizon, step, model_row.version, forecast_rows, quality, created_at, valid_until)
        predictions.append(
            {
                "site_id": site_id,
                "target": TARGET,
                "forecast": forecast_rows,
                "site_status_forecast": _status_forecast(status, profile, timestamps),
                "efficiency": _efficiency(context, status, workload, predicted_total),
                "quality": quality,
            }
        )

    session.commit()
    return {
        "created_at": created_at.isoformat(),
        "horizon": horizon,
        "step": step,
        "model_version": model_row.version,
        "predictions": predictions,
    }


def predict(request: PredictRequest | dict[str, Any]) -> dict[str, Any]:
    create_tables()
    with SessionLocal() as session:
        return _predict_with_session(request, session)
