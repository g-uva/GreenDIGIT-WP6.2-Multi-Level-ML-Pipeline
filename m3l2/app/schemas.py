from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class IngestRunRequest(BaseModel):
    start_ts: datetime | None = None
    end_ts: datetime | None = None
    sites: list[str] | None = None


class PredictRequest(BaseModel):
    site_ids: list[str] | None = None
    horizon: str = "24h"
    step: str = "1h"
    workload: dict[str, Any] | None = None
    use_cache: bool = True


class ForecastPoint(BaseModel):
    ts: str
    value: float


class SitePrediction(BaseModel):
    site_id: str
    target: str = "energy_wh"
    forecast: list[ForecastPoint]
    quality: dict[str, Any] = Field(default_factory=dict)

