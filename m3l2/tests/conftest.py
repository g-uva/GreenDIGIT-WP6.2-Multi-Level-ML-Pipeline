from __future__ import annotations

import os

import pytest

from m3l2.app.db import Base, configure_database, get_engine


@pytest.fixture()
def temp_database(tmp_path, monkeypatch):
    monkeypatch.setenv("M3L2_ENABLE_SCHEDULER", "false")
    db_path = tmp_path / "m3l2-test.db"
    engine = configure_database(f"sqlite:///{db_path}")
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=get_engine())

