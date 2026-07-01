from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from m3l2.app.db import ForecastCache, utc_now


def get_valid_cache(
    session: Session,
    site_id: str,
    target: str,
    horizon: str,
    step: str,
) -> ForecastCache | None:
    return session.execute(
        select(ForecastCache)
        .where(
            ForecastCache.site_id == site_id,
            ForecastCache.target == target,
            ForecastCache.horizon == horizon,
            ForecastCache.step == step,
            ForecastCache.valid_until > utc_now(),
        )
        .order_by(ForecastCache.created_at.desc())
    ).scalar_one_or_none()


def store_cache(
    session: Session,
    site_id: str,
    target: str,
    horizon: str,
    step: str,
    model_version: str,
    predictions: list[dict[str, Any]],
    quality: dict[str, Any],
    created_at: datetime,
    valid_until: datetime,
) -> ForecastCache:
    row = ForecastCache(
        site_id=site_id,
        target=target,
        horizon=horizon,
        step=step,
        created_at=created_at,
        valid_until=valid_until,
        model_version=model_version,
        predictions=predictions,
        quality=quality,
    )
    session.add(row)
    return row

