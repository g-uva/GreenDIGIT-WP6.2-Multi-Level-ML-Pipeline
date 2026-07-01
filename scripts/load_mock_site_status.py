#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from m3l2.app.db import SessionLocal, SiteProfile, SiteStatusSnapshot, create_tables, utc_now
from m3l2.ingestion.site_adapter import normalise_site_profile, normalise_site_status
from sqlalchemy import select


def _empty_to_none(row: dict) -> dict:
    return {key: (None if value == "" else value) for key, value in row.items()}


def load_profiles(path: Path) -> int:
    payload = json.loads(path.read_text())
    create_tables()
    count = 0
    with SessionLocal() as session:
        for item in payload:
            profile = normalise_site_profile(item)
            profile["updated_at"] = utc_now()
            existing = session.execute(select(SiteProfile).where(SiteProfile.site_id == profile["site_id"])).scalar_one_or_none()
            if existing is None:
                session.add(SiteProfile(**profile))
            else:
                for key, value in profile.items():
                    setattr(existing, key, value)
            count += 1
        session.commit()
    return count


def load_status(path: Path) -> int:
    create_tables()
    count = 0
    with path.open(newline="") as handle, SessionLocal() as session:
        for row in csv.DictReader(handle):
            payload = _empty_to_none(row)
            if payload.get("scheduled_maintenance"):
                payload["scheduled_maintenance"] = json.loads(payload["scheduled_maintenance"])
            status = normalise_site_status(payload)
            status["raw_json"] = {**payload, "source_file": str(path), "source_schema": "mock_site_status_snapshots"}
            session.add(SiteStatusSnapshot(**status, ingested_at=utc_now()))
            count += 1
        session.commit()
    return count


def main() -> int:
    parser = argparse.ArgumentParser(description="Load mock Site Adapter profile/status data into M3L2.")
    parser.add_argument("--profiles", default="raw_data/mock_site_profiles.json")
    parser.add_argument("--status", default="raw_data/mock_site_status_snapshots.csv")
    args = parser.parse_args()

    result = {"profiles": load_profiles(Path(args.profiles)), "status_rows": load_status(Path(args.status))}
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

