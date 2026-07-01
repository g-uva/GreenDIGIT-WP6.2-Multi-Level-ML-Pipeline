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
    include_site_status: bool = False


class SiteProfileIn(BaseModel):
    site_id: str
    ri_type: str = "unknown"
    location: str | None = None
    compute_capacity: float | None = None
    gpu_capacity: float | None = None
    storage_capacity: float | None = None
    network_topology: str | None = None
    link_capacities: dict[str, Any] | None = None
    supported_workload_types: list[str] | None = None
    energy_capabilities: dict[str, Any] | None = None
    static_pue_baseline: float | None = None
    raw_json: dict[str, Any] | None = None


class SiteStatusIn(BaseModel):
    site_id: str
    ri_type: str = "unknown"
    timestamp: datetime
    operational_status: str = "UP"
    maintenance_flag: bool = False
    scheduled_maintenance: dict[str, Any] | None = None
    node_availability: float | None = None
    link_availability: float | None = None
    stability_score: float | None = None
    packet_loss: float | None = None
    network_jitter: float | None = None
    network_utilization: float | None = None
    available_bandwidth: float | None = None
    cpu_util_avg: float | None = None
    gpu_util_avg: float | None = None
    free_cpu_capacity: float | None = None
    free_gpu_capacity: float | None = None
    queue_length: int | None = None
    remaining_jobs: int | None = None
    provisioning_delay_s: float | None = None
    load_index: float | None = None
    energy_consumed: float | None = None
    pue_estimate: float | None = None
    carbon_intensity: float | None = None
    energy_per_task_proxy: float | None = None
    update_frequency: float | None = None
    data_confidence: float | None = None
    coverage_ratio: float | None = None
    stale_flag: bool = False
    raw_json: dict[str, Any] | None = None


class ForecastPoint(BaseModel):
    ts: str
    value: float


class SitePrediction(BaseModel):
    site_id: str
    target: str = "energy_wh"
    forecast: list[ForecastPoint]
    quality: dict[str, Any] = Field(default_factory=dict)
