#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from m3l2.site_adapter.auth import create_site_jwt


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a 24-hour L2 Site Adapter JWT.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--site-id", required=True)
    parser.add_argument("--role", choices=["site_admin", "publisher", "reader"], default="site_admin")
    parser.add_argument("--ttl-hours", type=int, default=24)
    args = parser.parse_args()

    secret = os.getenv("JWT_SECRET")
    if not secret:
        print("JWT_SECRET must be set", file=sys.stderr)
        return 2
    print(create_site_jwt(args.email, args.site_id, args.role, secret, ttl_hours=args.ttl_hours))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
