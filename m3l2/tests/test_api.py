from __future__ import annotations

from fastapi.testclient import TestClient

from m3l2.app.main import app


def test_health_works(temp_database, monkeypatch):
    monkeypatch.setenv("M3L2_ENABLE_SCHEDULER", "false")
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_predict_no_active_model(temp_database, monkeypatch):
    monkeypatch.setenv("M3L2_ENABLE_SCHEDULER", "false")
    with TestClient(app) as client:
        response = client.post("/predict", json={"site_ids": None, "horizon": "24h", "step": "1h", "use_cache": True})
    assert response.status_code == 503
    assert response.json()["status"] == "no_active_model"

