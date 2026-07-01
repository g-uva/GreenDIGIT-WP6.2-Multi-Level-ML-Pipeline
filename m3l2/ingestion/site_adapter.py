from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


PROFILE_FIELDS = {
    "site_id",
    "ri_type",
    "location",
    "compute_capacity",
    "gpu_capacity",
    "storage_capacity",
    "network_topology",
    "link_capacities",
    "supported_workload_types",
    "energy_capabilities",
    "static_pue_baseline",
}

STATUS_FIELDS = {
    "site_id",
    "ri_type",
    "timestamp",
    "operational_status",
    "maintenance_flag",
    "scheduled_maintenance",
    "node_availability",
    "link_availability",
    "stability_score",
    "packet_loss",
    "network_jitter",
    "network_utilization",
    "available_bandwidth",
    "cpu_util_avg",
    "gpu_util_avg",
    "free_cpu_capacity",
    "free_gpu_capacity",
    "queue_length",
    "remaining_jobs",
    "provisioning_delay_s",
    "load_index",
    "energy_consumed",
    "pue_estimate",
    "carbon_intensity",
    "energy_per_task_proxy",
    "update_frequency",
    "data_confidence",
    "coverage_ratio",
    "stale_flag",
}


def _first(payload: dict[str, Any], *names: str) -> Any:
    for name in names:
        if name in payload and payload[name] not in (None, ""):
            return payload[name]
    return None


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    parsed = _float(value)
    return int(parsed) if parsed is not None else None


def _ts(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value in (None, ""):
        parsed = datetime.now(timezone.utc)
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _status(value: Any) -> str:
    normalized = str(value or "UP").strip().upper()
    return normalized if normalized in {"UP", "DOWN", "DEGRADED", "MAINTENANCE"} else "DEGRADED"


def normalise_site_profile(payload: dict[str, Any], adapter_type: str = "generic") -> dict[str, Any]:
    if adapter_type == "openstack":
        profile = {
            "site_id": _first(payload, "site_id", "cloud_name", "region_name", "name"),
            "ri_type": "cloud",
            "location": _first(payload, "location", "region_name", "availability_zone"),
            "compute_capacity": _float(_first(payload, "compute_capacity", "total_vcpus", "vcpus_total", "cpu_capacity")),
            "gpu_capacity": _float(_first(payload, "gpu_capacity", "total_gpus", "gpus_total")),
            "storage_capacity": _float(_first(payload, "storage_capacity", "total_disk_gb", "disk_gb_total")),
            "network_topology": _first(payload, "network_topology"),
            "link_capacities": _first(payload, "link_capacities", "networks"),
            "supported_workload_types": _first(payload, "supported_workload_types") or ["vm", "batch", "ml"],
            "energy_capabilities": _first(payload, "energy_capabilities") or {"metering": "optional"},
            "static_pue_baseline": _float(_first(payload, "static_pue_baseline", "pue")),
        }
    elif adapter_type == "iot":
        profile = {
            "site_id": _first(payload, "site_id", "site", "site_name"),
            "ri_type": "iot",
            "location": _first(payload, "location", "facility"),
            "compute_capacity": _float(_first(payload, "compute_capacity", "total_nodes", "node_count")),
            "gpu_capacity": _float(_first(payload, "gpu_capacity")),
            "storage_capacity": _float(_first(payload, "storage_capacity")),
            "network_topology": _first(payload, "network_topology", "topology"),
            "link_capacities": _first(payload, "link_capacities"),
            "supported_workload_types": _first(payload, "supported_workload_types") or ["stream", "iot", "network"],
            "energy_capabilities": _first(payload, "energy_capabilities") or {"hermis": True, "metering": "estimated"},
            "static_pue_baseline": _float(_first(payload, "static_pue_baseline", "pue")),
        }
    else:
        profile = {field: payload.get(field) for field in PROFILE_FIELDS}

    if not profile.get("site_id"):
        raise ValueError("site profile requires site_id")
    profile["ri_type"] = profile.get("ri_type") or "unknown"
    profile["raw_json"] = payload
    return profile


def normalise_site_status(payload: dict[str, Any], adapter_type: str = "generic") -> dict[str, Any]:
    if adapter_type == "openstack":
        total_vcpus = _float(_first(payload, "total_vcpus", "vcpus_total", "compute_capacity"))
        free_vcpus = _float(_first(payload, "free_vcpus", "vcpus_free", "free_cpu_capacity"))
        total_gpus = _float(_first(payload, "total_gpus", "gpus_total", "gpu_capacity"))
        free_gpus = _float(_first(payload, "free_gpus", "gpus_free", "free_gpu_capacity"))
        cpu_util = None if total_vcpus in (None, 0) or free_vcpus is None else max(0.0, min(100.0, 100.0 * (1.0 - free_vcpus / total_vcpus)))
        gpu_util = None if total_gpus in (None, 0) or free_gpus is None else max(0.0, min(100.0, 100.0 * (1.0 - free_gpus / total_gpus)))
        status = {
            "site_id": _first(payload, "site_id", "cloud_name", "region_name", "name"),
            "ri_type": "cloud",
            "timestamp": _ts(_first(payload, "timestamp", "ts", "updated_at")),
            "operational_status": _status(_first(payload, "operational_status", "state", "status")),
            "maintenance_flag": bool(_first(payload, "maintenance_flag", "maintenance", "planned_maintenance") or False),
            "free_cpu_capacity": free_vcpus,
            "free_gpu_capacity": free_gpus,
            "cpu_util_avg": _float(_first(payload, "cpu_util_avg")) if _first(payload, "cpu_util_avg") is not None else cpu_util,
            "gpu_util_avg": _float(_first(payload, "gpu_util_avg")) if _first(payload, "gpu_util_avg") is not None else gpu_util,
            "queue_length": _int(_first(payload, "queue_length", "pending_vms", "pending_jobs")),
            "remaining_jobs": _int(_first(payload, "remaining_jobs", "active_vms", "running_jobs")),
            "provisioning_delay_s": _float(_first(payload, "provisioning_delay_s", "vm_provisioning_delay_s")),
        }
    elif adapter_type == "iot":
        alive = _float(_first(payload, "alive_nodes", "active_nodes"))
        total = _float(_first(payload, "total_nodes", "node_count"))
        active_links = _float(_first(payload, "active_links"))
        total_links = _float(_first(payload, "total_links"))
        status = {
            "site_id": _first(payload, "site_id", "site", "site_name"),
            "ri_type": "iot",
            "timestamp": _ts(_first(payload, "timestamp", "ts", "bucket_15m")),
            "operational_status": _status(_first(payload, "operational_status", "state", "status")),
            "maintenance_flag": bool(_first(payload, "maintenance_flag", "maintenance") or False),
            "node_availability": None if total in (None, 0) or alive is None else alive / total,
            "link_availability": None if total_links in (None, 0) or active_links is None else active_links / total_links,
            "packet_loss": _float(_first(payload, "packet_loss", "packet_loss_percent")),
            "network_jitter": _float(_first(payload, "network_jitter", "jitter_ms")),
            "network_utilization": _float(_first(payload, "network_utilization")),
            "available_bandwidth": _float(_first(payload, "available_bandwidth", "available_bandwidth_mbps")),
            "queue_length": _int(_first(payload, "queue_length", "pending_jobs")),
            "remaining_jobs": _int(_first(payload, "remaining_jobs", "running_jobs")),
        }
    else:
        status = {field: payload.get(field) for field in STATUS_FIELDS}
        status["timestamp"] = _ts(status.get("timestamp"))
        status["operational_status"] = _status(status.get("operational_status"))

    if not status.get("site_id"):
        raise ValueError("site status requires site_id")
    status["ri_type"] = status.get("ri_type") or payload.get("ri_type") or "unknown"
    status["timestamp"] = status.get("timestamp") or _ts(payload.get("timestamp"))
    status["operational_status"] = _status(status.get("operational_status"))
    status["maintenance_flag"] = bool(status.get("maintenance_flag") or False)
    status["stale_flag"] = bool(status.get("stale_flag") or False)
    status["scheduled_maintenance"] = _first(payload, "scheduled_maintenance")
    status["energy_consumed"] = _float(_first(payload, "energy_consumed", "energy_wh"))
    status["pue_estimate"] = _float(_first(payload, "pue_estimate", "pue"))
    status["carbon_intensity"] = _float(_first(payload, "carbon_intensity", "ci_gco2_kwh"))
    status["energy_per_task_proxy"] = _float(_first(payload, "energy_per_task_proxy"))
    status["update_frequency"] = _float(_first(payload, "update_frequency"))
    status["data_confidence"] = _float(_first(payload, "data_confidence"))
    status["coverage_ratio"] = _float(_first(payload, "coverage_ratio"))
    status["load_index"] = _float(_first(payload, "load_index"))
    status["raw_json"] = payload
    return status
