from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from m3l2.app.config import get_settings
from m3l2.app.db import ExecutionRecord, ForecastCache, ModelRegistry, SessionLocal, create_tables
from m3l2.app.schemas import IngestRunRequest, PredictRequest
from m3l2.inference.predict import predict as run_predict
from m3l2.ingestion.jobs import run_ingestion
from m3l2.training.registry import get_active_model, get_model_by_version, list_models, serialise_model
from m3l2.training.train import train_model

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger(__name__)
scheduler: BackgroundScheduler | None = None


def _schema_dump(model: Any) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model.dict()


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


app = FastAPI(title="M3L2 MVP API", version="0.1.0", lifespan=lifespan)


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
        "models_count": session.scalar(select(func.count()).select_from(ModelRegistry)),
        "active_model_version": active.version if active else None,
        "latest_ingested_at": latest_ingested_at.isoformat() if latest_ingested_at else None,
        "forecast_cache_count": session.scalar(select(func.count()).select_from(ForecastCache)),
    }
