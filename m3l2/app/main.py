from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Body, Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from m3l2.app.config import get_settings
from m3l2.app.db import (
    ExecutionRecord,
    ForecastCache,
    ModelRegistry,
    RegisteredSite,
    SessionLocal,
    SiteProfile,
    SiteSnapshot,
    SiteStatusSnapshot,
    create_tables,
    utc_now,
)
from m3l2.app.schemas import IngestRunRequest, PredictRequest
from m3l2.auth.router import router as auth_router
from m3l2.broker_mock.router import router as mock_broker_router
from m3l2.inference.predict import predict as run_predict
from m3l2.ingestion.jobs import run_ingestion
from m3l2.ingestion.site_adapter import normalise_site_profile, normalise_site_status
from m3l2.site_adapter.control_plane import router as site_adapter_router
from m3l2.training.registry import get_active_model, get_model_by_version, list_models, serialise_model
from m3l2.training.train import train_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
scheduler: BackgroundScheduler | None = None


def _schema_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


def _parse_optional_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialise_dt(value: Any) -> Any:
    return value.isoformat() if isinstance(value, datetime) else value


def _serialise_row(row: Any) -> dict[str, Any]:
    return {column.name: _serialise_dt(getattr(row, column.name)) for column in row.__table__.columns}


def get_db() -> Session:
    with SessionLocal() as session:
        yield session


def _scheduled_cycle() -> None:
    logger.info("Starting scheduled M3L2 ingestion and training cycle")
    try:
        ingestion_summary = run_ingestion()
        training_summary = train_model(force=False)
        logger.info("Scheduled M3L2 cycle completed: ingestion=%s training=%s", ingestion_summary, training_summary)
    except Exception:
        logger.exception("Scheduled M3L2 cycle failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global scheduler
    create_tables()
    settings = get_settings()
    if settings.enable_scheduler and (scheduler is None or not scheduler.running):
        scheduler = BackgroundScheduler(timezone="UTC")
        scheduler.add_job(
            _scheduled_cycle,
            "interval",
            hours=settings.train_interval_hours,
            id="m3l2_ingest_train",
            max_instances=1,
            coalesce=True,
            replace_existing=True,
        )
        scheduler.start()
        logger.info("Started M3L2 scheduler with %sh interval", settings.train_interval_hours)
    yield
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Stopped M3L2 scheduler")


app = FastAPI(
    title="GreenDIGIT M3L2 MVP API",
    version="0.1.0",
    lifespan=lifespan,
    description=(
        "M3L2 L2DB, Site Adapter Control Plane, prediction API, and mock broker flow.\n\n"
        "**Authentication**\n\n"
        "- Open `/auth/login` to obtain a 24-hour JWT using email and password.\n"
        "- The first login registers a password only if the email is listed in `allowed_emails.txt`.\n"
        "- Use the token as `Authorization: Bearer <token>` on protected L2 endpoints.\n"
        "- JSON token clients can call `POST /auth/token` or `GET /auth/token`."
    ),
    swagger_ui_parameters={"persistAuthorization": True},
)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(auth_router)
app.include_router(site_adapter_router)
app.include_router(mock_broker_router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/auth/login")


@app.get("/health")
def health(session: Session = Depends(get_db)) -> dict[str, Any]:
    active = get_active_model(session)
    return {"status": "ok", "db": "ok", "active_model_version": active.version if active else None}


@app.post("/ingest/run")
def ingest_run(request: IngestRunRequest | None = None) -> dict[str, Any]:
    payload = _schema_dump(request) if request else {}
    return run_ingestion(**payload)


@app.post("/train")
def train() -> dict[str, Any]:
    return train_model(force=True)


@app.post("/predict")
def predict(request: PredictRequest):
    try:
        result = run_predict(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if result.get("status") == "no_active_model":
        return JSONResponse(status_code=503, content=result)
    return result


@app.post("/predict/batch")
def predict_batch(requests: list[PredictRequest]):
    responses = []
    status_code = 200
    for request in requests:
        result = run_predict(request)
        if result.get("status") == "no_active_model":
            status_code = 503
        responses.append(result)
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=responses)
    return responses


@app.get("/models")
def models(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [serialise_model(row) for row in list_models(session)]


@app.get("/models/{version}")
def model(version: str, session: Session = Depends(get_db)) -> dict[str, Any]:
    row = get_model_by_version(session, version)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Model version not found: {version}")
    return serialise_model(row)


@app.get("/metrics")
def metrics(session: Session = Depends(get_db)) -> dict[str, Any]:
    active = get_active_model(session)
    latest_ingested_at = session.execute(select(ExecutionRecord.ingested_at).order_by(desc(ExecutionRecord.ingested_at))).scalars().first()
    return {
        "execution_records_count": session.scalar(select(func.count()).select_from(ExecutionRecord)),
        "site_profiles_count": session.scalar(select(func.count()).select_from(SiteProfile)),
        "site_status_snapshots_count": session.scalar(select(func.count()).select_from(SiteStatusSnapshot)),
        "models_count": session.scalar(select(func.count()).select_from(ModelRegistry)),
        "registered_sites_count": session.scalar(select(func.count()).select_from(RegisteredSite)),
        "site_snapshots_count": session.scalar(select(func.count()).select_from(SiteSnapshot)),
        "active_model_version": active.version if active else None,
        "latest_ingested_at": latest_ingested_at.isoformat() if latest_ingested_at else None,
        "forecast_cache_count": session.scalar(select(func.count()).select_from(ForecastCache)),
    }


@app.post("/site-profiles")
def upsert_site_profiles(
    payload: dict[str, Any] | list[dict[str, Any]] = Body(...),
    adapter_type: str = "generic",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    items = payload if isinstance(payload, list) else [payload]
    upserted = 0
    for item in items:
        profile = normalise_site_profile(item, adapter_type=adapter_type)
        existing = session.execute(select(SiteProfile).where(SiteProfile.site_id == profile["site_id"])).scalar_one_or_none()
        profile["updated_at"] = utc_now()
        if existing is None:
            session.add(SiteProfile(**profile))
        else:
            for key, value in profile.items():
                setattr(existing, key, value)
        upserted += 1
    session.commit()
    return {"upserted": upserted, "adapter_type": adapter_type}


@app.get("/site-profiles")
def list_site_profiles(session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    return [_serialise_row(row) for row in session.execute(select(SiteProfile).order_by(SiteProfile.site_id)).scalars()]


@app.post("/site-status")
def ingest_site_status(
    payload: dict[str, Any] | list[dict[str, Any]] = Body(...),
    adapter_type: str = "generic",
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    items = payload if isinstance(payload, list) else [payload]
    inserted = 0
    for item in items:
        status = normalise_site_status(item, adapter_type=adapter_type)
        session.add(SiteStatusSnapshot(**status, ingested_at=utc_now()))
        inserted += 1
    session.commit()
    return {"inserted": inserted, "adapter_type": adapter_type}


@app.get("/site-status/latest")
def latest_site_status(site_id: str | None = None, session: Session = Depends(get_db)) -> list[dict[str, Any]]:
    sites = [site_id] if site_id else [
        site for site in session.execute(select(SiteStatusSnapshot.site_id).distinct()).scalars().all() if site
    ]
    rows = []
    for site in sites:
        row = session.execute(
            select(SiteStatusSnapshot)
            .where(SiteStatusSnapshot.site_id == site)
            .order_by(desc(SiteStatusSnapshot.timestamp))
        ).scalars().first()
        if row:
            rows.append(_serialise_row(row))
    return rows


@app.delete("/control/execution-records")
def delete_execution_records(
    source: str | None = None,
    site_id: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
    dry_run: bool = True,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(ExecutionRecord)
    if site_id:
        query = query.where(ExecutionRecord.site_id == site_id)
    start = _parse_optional_ts(start_ts)
    end = _parse_optional_ts(end_ts)
    if start:
        query = query.where(ExecutionRecord.start_ts >= start)
    if end:
        query = query.where(ExecutionRecord.start_ts < end)

    matched = []
    for row in session.execute(query).scalars():
        if source and (row.raw_json or {}).get("source_file") != source:
            continue
        matched.append(row)

    if not dry_run:
        for row in matched:
            session.delete(row)
        session.commit()

    return {"matched": len(matched), "deleted": 0 if dry_run else len(matched), "dry_run": dry_run}


@app.delete("/control/site-status")
def delete_site_status(
    source: str | None = None,
    site_id: str | None = None,
    start_ts: str | None = None,
    end_ts: str | None = None,
    dry_run: bool = True,
    session: Session = Depends(get_db),
) -> dict[str, Any]:
    query = select(SiteStatusSnapshot)
    if site_id:
        query = query.where(SiteStatusSnapshot.site_id == site_id)
    start = _parse_optional_ts(start_ts)
    end = _parse_optional_ts(end_ts)
    if start:
        query = query.where(SiteStatusSnapshot.timestamp >= start)
    if end:
        query = query.where(SiteStatusSnapshot.timestamp < end)

    matched = []
    for row in session.execute(query).scalars():
        if source and (row.raw_json or {}).get("source_file") != source:
            continue
        matched.append(row)
    if not dry_run:
        for row in matched:
            session.delete(row)
        session.commit()
    return {"matched": len(matched), "deleted": 0 if dry_run else len(matched), "dry_run": dry_run}
