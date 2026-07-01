#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from m3l2.ingestion.raw_aggregate import load_summary_sites_15m


def post_train(api_url: str) -> dict:
    request = urllib.request.Request(
        f"{api_url.rstrip('/')}/train",
        data=b"",
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Load summary_sites_15m.csv into M3L2 and trigger /train.")
    parser.add_argument("--csv", default="raw_data/summary_sites_15m.csv", help="Path to the 15-minute aggregate CSV.")
    parser.add_argument("--api-url", default="http://localhost:8000", help="M3L2 API base URL.")
    parser.add_argument("--source", default=None, help="Source tag stored in raw_json.source_file.")
    args = parser.parse_args()

    load_summary = load_summary_sites_15m(Path(args.csv), source=args.source)
    train_summary = post_train(args.api_url)
    print(json.dumps({"load": load_summary, "train": train_summary}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
