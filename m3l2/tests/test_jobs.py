from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select

from m3l2.app.db import ExecutionRecord, SessionLocal
from m3l2.ingestion.jobs import run_ingestion
from m3l2.ingestion.metricsdb_client import MetricsDBClient


def test_run_ingestion_upserts_duplicate_exec_unit_id(monkeypatch, temp_database):
    calls = {"n": 0}

    def fake_fetch(self, start_ts, end_ts, sites=None):
        calls["n"] += 1
        return [
            {
                "ExecUnitID": "dup-1",
                "Site": "site-a",
                "StartExecTime": "2026-01-01T00:00:00Z",
                "Energy_wh": 1.0 if calls["n"] == 1 else 2.0,
            }
        ]

    monkeypatch.setattr(MetricsDBClient, "fetch_execution_records", fake_fetch)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)
    first = run_ingestion(start, end)
    second = run_ingestion(start, end)

    assert first["inserted"] == 1
    assert second["updated"] == 1
    with SessionLocal() as session:
        rows = session.execute(select(ExecutionRecord)).scalars().all()
        assert len(rows) == 1
        assert rows[0].energy_wh == 2.0

