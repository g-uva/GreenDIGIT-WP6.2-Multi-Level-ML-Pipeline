from __future__ import annotations

import logging
import math
from datetime import timezone
from pathlib import Path
from typing import Any

import joblib
import pandas as pd
from sqlalchemy import select

from m3l2.app.config import get_settings
from m3l2.app.db import ExecutionRecord, ModelRegistry, SessionLocal, create_tables, utc_now
from m3l2.training.features import build_training_frame

logger = logging.getLogger(__name__)

TARGET = "energy_wh"
CATEGORICAL_FEATURES = ["site_id", "ri_type"]
NUMERIC_FEATURES = [
    "duration_s",
    "work",
    "hour",
    "day_of_week",
    "records_count_site_24h",
    "rolling_energy_mean_site_24h",
    "rolling_work_mean_site_24h",
]
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES


def _make_pipeline() -> Any:
    from sklearn.compose import ColumnTransformer
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import OneHotEncoder, StandardScaler

    categorical = Pipeline(
        steps=[
            ("imputer", SimpleImputer(strategy="constant", fill_value="unknown")),
            ("onehot", OneHotEncoder(handle_unknown="ignore")),
        ]
    )
    numeric = Pipeline(steps=[("imputer", SimpleImputer(strategy="median")), ("scaler", StandardScaler())])
    preprocessor = ColumnTransformer(
        transformers=[
            ("categorical", categorical, CATEGORICAL_FEATURES),
            ("numeric", numeric, NUMERIC_FEATURES),
        ]
    )
    return Pipeline(
        steps=[
            ("preprocessor", preprocessor),
            ("model", RandomForestRegressor(n_estimators=80, random_state=42, n_jobs=-1)),
        ]
    )


def _metrics(y_true: pd.Series, y_pred: Any, n_train: int, n_val: int) -> dict[str, Any]:
    if n_val == 0:
        return {"mae": None, "rmse": None, "n_train": n_train, "n_val": n_val}
    errors = [float(abs(a - b)) for a, b in zip(y_true, y_pred)]
    squared = [float((a - b) ** 2) for a, b in zip(y_true, y_pred)]
    return {
        "mae": float(sum(errors) / len(errors)),
        "rmse": float(math.sqrt(sum(squared) / len(squared))),
        "n_train": n_train,
        "n_val": n_val,
    }


def _version(now) -> str:
    return f"energy-wh-{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%S')}"


def train_model(force: bool = False) -> dict[str, Any]:
    create_tables()
    settings = get_settings()
    with SessionLocal() as session:
        df = build_training_frame(session)
        if len(df) < settings.min_training_records:
            return {
                "status": "not_enough_data",
                "n_records": len(df),
                "min_training_records": settings.min_training_records,
            }

        df = df.sort_values("start_ts").reset_index(drop=True)
        val_size = max(1, int(len(df) * 0.2)) if len(df) >= 5 else 0
        train_df = df.iloc[:-val_size] if val_size else df
        val_df = df.iloc[-val_size:] if val_size else df.iloc[0:0]

        pipeline = _make_pipeline()
        pipeline.fit(train_df[FEATURE_COLUMNS], train_df[TARGET])
        val_pred = pipeline.predict(val_df[FEATURE_COLUMNS]) if val_size else []
        metrics = _metrics(val_df[TARGET], val_pred, len(train_df), len(val_df))

        now = utc_now()
        version = _version(now)
        model_dir = Path(settings.model_dir)
        model_dir.mkdir(parents=True, exist_ok=True)
        model_path = model_dir / f"{version}.joblib"
        feature_schema = {
            "categorical": CATEGORICAL_FEATURES,
            "numeric": NUMERIC_FEATURES,
            "target": TARGET,
        }
        joblib.dump({"pipeline": pipeline, "feature_schema": feature_schema, "version": version}, model_path)

        for row in session.execute(
            select(ModelRegistry).where(ModelRegistry.target == TARGET, ModelRegistry.active.is_(True))
        ).scalars():
            row.active = False
        registry_row = ModelRegistry(
            model_name="random_forest_mvp",
            target=TARGET,
            version=version,
            path=str(model_path),
            trained_at=now,
            training_window_start=df["start_ts"].min().to_pydatetime(),
            training_window_end=df["start_ts"].max().to_pydatetime(),
            metrics=metrics,
            feature_schema=feature_schema,
            active=True,
        )
        session.add(registry_row)
        session.commit()

        sites = session.execute(select(ExecutionRecord.site_id).distinct()).scalars().all()

    forecast_status = "skipped"
    if sites:
        from m3l2.app.schemas import PredictRequest
        from m3l2.inference.predict import predict

        result = predict(PredictRequest(site_ids=[site for site in sites if site], use_cache=False))
        forecast_status = result.get("status", "stored")

    logger.info("Training completed for %s with metrics %s", version, metrics)
    return {
        "status": "trained",
        "model_version": version,
        "path": str(model_path),
        "metrics": metrics,
        "forecast_status": forecast_status,
    }
