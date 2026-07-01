from __future__ import annotations

from m3l2.ingestion.normalise import normalise_execution_record


def test_normalise_cloud_payload():
    result = normalise_execution_record(
        {
            "ExecUnitID": "job-1",
            "Site": "site-a",
            "StartExecTime": "2026-01-01T00:00:00Z",
            "StopExecTime": "2026-01-01T01:00:00Z",
            "Energy_wh": "12.5",
            "cloud_type": "vm",
            "CPUTime": 99,
        }
    )
    assert result["exec_unit_id"] == "job-1"
    assert result["site_id"] == "site-a"
    assert result["ri_type"] == "cloud"
    assert result["work_type"] == "cpu_time"
    assert result["energy_wh"] == 12.5


def test_normalise_network_payload():
    result = normalise_execution_record(
        {
            "exec_unit_id": "net-1",
            "site": "site-b",
            "start_ts": "2026-01-01T00:00:00+00:00",
            "network_type": "wan",
            "AmountOfDataTransferred": 123,
        }
    )
    assert result["ri_type"] == "network"
    assert result["work_type"] == "data_transfer"


def test_normalise_unknown_payload_derives_id():
    result = normalise_execution_record({"site_name": "x", "start_ts": "2026-01-01T00:00:00Z"})
    assert result["exec_unit_id"].startswith("derived-")
    assert result["ri_type"] == "unknown"

