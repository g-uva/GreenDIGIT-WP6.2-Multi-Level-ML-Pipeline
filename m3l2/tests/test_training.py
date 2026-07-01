from __future__ import annotations

from m3l2.training.train import train_model


def test_train_model_not_enough_data(temp_database):
    result = train_model(force=True)
    assert result["status"] == "not_enough_data"
    assert result["n_records"] == 0

