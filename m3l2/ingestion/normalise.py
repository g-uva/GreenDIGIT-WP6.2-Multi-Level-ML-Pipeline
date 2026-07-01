from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

FIELD_ALIASES = {
    "exec_unit_id": ["ExecUnitID", "exec_unit_id", "execUnitId", "execution_unit_id"],
    "site_id": ["Site", "site", "site_name", "SiteName"],
    "energy_wh": ["Energy_wh", "energy_wh", "EnergyWh", "energy_Wh"],
    "work": ["Work", "work"],
    "start_ts": ["StartExecTime", "start_exec_time", "start_ts"],
    "stop_ts": ["StopExecTime", "stop_exec_time", "stop_ts"],
    "status": ["Status", "status"],
    "owner": ["Owner", "owner"],
    "network_type": ["NetworkType", "network_type"],
    "cloud_type": ["cloud_type", "CloudType"],
    "compute_service": ["compute_service", "ComputeService"],
}


def _first(raw: dict[str, Any], names: list[str]) -> Any:
    for name in names:
        if name in raw and raw[name] not in ("", None):
            return raw[name]
    return None


def _parse_ts(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, (int, float)):
        parsed = datetime.fromtimestamp(float(value), tz=timezone.utc)
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            try:
                parsed = datetime.strptime(text, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                return None
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


def _stable_exec_unit_id(site_id: str, start_ts: datetime | None, raw: dict[str, Any]) -> str:
    payload = json.dumps(raw, sort_keys=True, default=str)
    digest = hashlib.sha256(f"{site_id}|{start_ts}|{payload}".encode("utf-8")).hexdigest()[:32]
    return f"derived-{digest}"


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return _parse_ts(value).isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)


def _ri_type(raw: dict[str, Any]) -> str:
    network_type = _first(raw, FIELD_ALIASES["network_type"])
    if network_type:
        if "iot" in str(network_type).lower():
            return "iot"
        return "network"
    if _first(raw, FIELD_ALIASES["cloud_type"]) or _first(raw, FIELD_ALIASES["compute_service"]):
        return "cloud"
    return "unknown"


def _work_type(raw: dict[str, Any]) -> str:
    if _first(raw, ["AmountOfDataTransferred", "amount_of_data_transferred"]) is not None:
        return "data_transfer"
    for key in raw:
        lowered = key.lower()
        if "cpu" in lowered or "wallclock" in lowered or "wall_clock" in lowered:
            return "cpu_time"
    return "unknown"


def normalise_execution_record(raw: dict[str, Any]) -> dict[str, Any]:
    if not raw:
        raise ValueError("empty execution payload")

    site_id = str(_first(raw, FIELD_ALIASES["site_id"]) or "unknown-site")
    start_ts = _parse_ts(_first(raw, FIELD_ALIASES["start_ts"]))
    stop_ts = _parse_ts(_first(raw, FIELD_ALIASES["stop_ts"]))
    if start_ts is None:
        raise ValueError("execution record has no parseable start timestamp")
    if stop_ts is not None and stop_ts < start_ts:
        raise ValueError("execution record stop timestamp is before start timestamp")

    exec_unit_id = _first(raw, FIELD_ALIASES["exec_unit_id"])
    if exec_unit_id in (None, ""):
        exec_unit_id = _stable_exec_unit_id(site_id, start_ts, raw)

    return {
        "exec_unit_id": str(exec_unit_id),
        "site_id": site_id,
        "ri_type": _ri_type(raw),
        "start_ts": start_ts,
        "stop_ts": stop_ts,
        "status": _first(raw, FIELD_ALIASES["status"]),
        "energy_wh": _float_or_none(_first(raw, FIELD_ALIASES["energy_wh"])),
        "work": _float_or_none(_first(raw, FIELD_ALIASES["work"])),
        "work_type": _work_type(raw),
        "owner": _first(raw, FIELD_ALIASES["owner"]),
        "raw_json": _json_safe(raw),
    }
