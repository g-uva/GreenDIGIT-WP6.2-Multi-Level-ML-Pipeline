from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

RIType = Literal["cloud", "network", "grid"]
AuthType = Literal["jwt", "egi_checkin", "none"]
SnapshotSource = Literal["push", "pull"]


class SiteRegistrationRequest(BaseModel):
    site_id: str
    site_name: str
    ri_type: RIType = "grid"
    adapter_base_url: str
    contact_email: str
    auth_type: AuthType = "jwt"
    auth_config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class SiteSnapshotIn(BaseModel):
    ts: datetime
    capabilities: dict[str, Any] = Field(default_factory=dict)
    availability: dict[str, Any] = Field(default_factory=dict)
    usage: dict[str, Any] = Field(default_factory=dict)
    efficiency: dict[str, Any] = Field(default_factory=dict)
    status: dict[str, Any] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)


class SiteSnapshotOut(SiteSnapshotIn):
    id: int
    site_id: str
    source: SnapshotSource
    raw_json: dict[str, Any] | None = None


class WorkloadSubmissionRequest(BaseModel):
    workload_id: str
    workload_type: str
    requirements: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
