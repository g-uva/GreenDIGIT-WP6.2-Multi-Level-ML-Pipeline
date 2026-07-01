from __future__ import annotations

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from m3l2.app.db import ExecutionRecord

FEATURE_COLUMNS = [
    "site_id",
    "ri_type",
    "start_ts",
    "duration_s",
    "energy_wh",
    "work",
    "hour",
    "day_of_week",
    "records_count_site_24h",
    "rolling_energy_mean_site_24h",
    "rolling_work_mean_site_24h",
]


def build_training_frame(session: Session) -> pd.DataFrame:
    rows = session.execute(select(ExecutionRecord)).scalars().all()
    if not rows:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    data = [
        {
            "site_id": row.site_id or "unknown-site",
            "ri_type": row.ri_type or "unknown",
            "start_ts": row.start_ts,
            "stop_ts": row.stop_ts,
            "energy_wh": row.energy_wh,
            "work": row.work,
        }
        for row in rows
    ]
    df = pd.DataFrame(data)
    df["start_ts"] = pd.to_datetime(df["start_ts"], utc=True)
    df["stop_ts"] = pd.to_datetime(df["stop_ts"], utc=True)
    df = df[df["energy_wh"].notna() & (df["energy_wh"] > 0)].copy()
    if df.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS)

    durations = (df["stop_ts"] - df["start_ts"]).dt.total_seconds()
    valid_durations = durations[durations.notna() & (durations >= 0)]
    median_duration = float(valid_durations.median()) if not valid_durations.empty else 0.0
    df["duration_s"] = durations.fillna(median_duration).clip(lower=0)
    df["work"] = pd.to_numeric(df["work"], errors="coerce").fillna(0.0)
    df["hour"] = df["start_ts"].dt.hour
    df["day_of_week"] = df["start_ts"].dt.dayofweek
    df.sort_values(["site_id", "start_ts"], inplace=True)

    rolling_frames = []
    for _, group in df.groupby("site_id", sort=False):
        group = group.sort_values("start_ts").set_index("start_ts")
        group["records_count_site_24h"] = group["energy_wh"].rolling("24h", min_periods=1).count().to_numpy()
        group["rolling_energy_mean_site_24h"] = group["energy_wh"].rolling("24h", min_periods=1).mean().to_numpy()
        group["rolling_work_mean_site_24h"] = group["work"].rolling("24h", min_periods=1).mean().to_numpy()
        rolling_frames.append(group.reset_index())

    df = pd.concat(rolling_frames, ignore_index=True).sort_values("start_ts")
    return df[FEATURE_COLUMNS].reset_index(drop=True)

