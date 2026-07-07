from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body

router = APIRouter(
    prefix="/mock-l3/sites",
    tags=["Mock L3 Site Adapter"],
    responses={404: {"description": "Mock site endpoint not found"}},
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.get(
    "/{site_id}/capabilities",
    summary="Mock L3 capabilities",
    description=(
        "Returns a static capabilities payload for L2 control-plane validation. "
        "Use this as the target for a registered site's `adapter_base_url` during local tests."
    ),
)
def capabilities(site_id: str) -> dict[str, Any]:
    return {
        "site_id": site_id,
        "ri_type": "grid",
        "supported_workload_types": ["batch", "ml", "network-transfer"],
        "resources": {
            "cpu_cores": 64,
            "gpu_count": 0,
            "storage_tb": 10,
            "network_gbps": 10,
        },
        "mock": True,
        "ts": _now(),
    }


@router.get(
    "/{site_id}/availability",
    summary="Mock L3 availability",
    description="Returns a static `status=up` availability payload for L2 pull tests.",
)
def availability(site_id: str) -> dict[str, Any]:
    return {
        "site_id": site_id,
        "status": "up",
        "maintenance": False,
        "node_availability": 0.95,
        "available_cpu_cores": 48,
        "queue_length": 2,
        "mock": True,
        "ts": _now(),
    }


@router.get(
    "/{site_id}/usage",
    summary="Mock L3 usage",
    description="Returns synthetic usage metrics for the requested time window and step.",
)
def usage(site_id: str, start: str | None = None, end: str | None = None, step: str = "1h") -> dict[str, Any]:
    return {
        "site_id": site_id,
        "window": {"start": start, "end": end, "step": step},
        "cpu_util_avg": 0.42,
        "memory_util_avg": 0.37,
        "network_util_avg": 0.21,
        "energy_wh": 1250.0,
        "mock": True,
        "ts": _now(),
    }


@router.get(
    "/{site_id}/efficiency",
    summary="Mock L3 efficiency",
    description="Returns synthetic PUE, carbon intensity, and energy-per-work metrics.",
)
def efficiency(site_id: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    return {
        "site_id": site_id,
        "window": {"start": start, "end": end},
        "pue_estimate": 1.35,
        "carbon_intensity_g_per_kwh": 270.0,
        "energy_per_cpu_hour_wh": 18.5,
        "mock": True,
        "ts": _now(),
    }


@router.post(
    "/{site_id}/submit-workload",
    summary="Mock L3 workload submission",
    description="Accepts any workload payload and returns a mock accepted submission response.",
    include_in_schema=False,
)
def submit_workload(site_id: str, payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    return {
        "site_id": site_id,
        "accepted": True,
        "submission_id": f"mock-{site_id}-{int(datetime.now(timezone.utc).timestamp())}",
        "received": payload,
        "mock": True,
        "ts": _now(),
    }
