from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


class SiteAdapterClient:
    def __init__(self, base_url: str, timeout_s: float = 15.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.get(f"{self.base_url}{path}", params=params)
            response.raise_for_status()
            payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout_s) as client:
            response = await client.post(f"{self.base_url}{path}", json=payload)
            response.raise_for_status()
            body = response.json()
        return body if isinstance(body, dict) else {"data": body}

    async def pull_snapshot(
        self,
        start: datetime | None = None,
        end: datetime | None = None,
        step: str = "1h",
    ) -> dict[str, Any]:
        end = end or datetime.now(timezone.utc)
        start = start or (end - timedelta(hours=24))
        window = {"start": start.isoformat(), "end": end.isoformat()}
        capabilities = await self._get("/capabilities")
        availability = await self._get("/availability")
        usage = await self._get("/usage", params={**window, "step": step})
        efficiency = await self._get("/efficiency", params=window)
        return {
            "capabilities": capabilities,
            "availability": availability,
            "usage": usage,
            "efficiency": efficiency,
        }

    async def submit_workload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._post("/submit-workload", payload)
