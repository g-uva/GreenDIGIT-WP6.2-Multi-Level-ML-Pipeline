from __future__ import annotations

import base64
import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from m3l2.app.config import get_settings
from m3l2.app.db import AuthUser, SessionLocal

SiteRole = Literal["site_admin", "publisher", "reader"]
security = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class SitePrincipal:
    email: str
    site_id: str
    role: SiteRole


def _encode_segment(value: dict) -> str:
    encoded = json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(encoded).rstrip(b"=").decode("ascii")


def _decode_segment(segment: str) -> bytes:
    padding = "=" * (-len(segment) % 4)
    try:
        return base64.urlsafe_b64decode(segment + padding)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from exc


def _decode_json_segment(segment: str) -> dict:
    try:
        value = json.loads(_decode_segment(segment))
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid bearer token") from exc
    if not isinstance(value, dict):
        raise HTTPException(status_code=401, detail="Invalid bearer token")
    return value


def _verify_hs256_jwt(token: str, secret: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(status_code=401, detail="Invalid bearer token")

    header = _decode_json_segment(parts[0])
    if header.get("alg") != "HS256":
        raise HTTPException(status_code=401, detail="Only HS256 JWTs are supported for the MVP")

    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    supplied = _decode_segment(parts[2])
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="Invalid bearer token signature")

    payload = _decode_json_segment(parts[1])
    now = datetime.now(timezone.utc).timestamp()
    ttl_seconds = get_settings().jwt_token_ttl_hours * 3600
    try:
        exp = float(payload["exp"])
        iat = float(payload.get("iat", now))
        if exp < now:
            raise HTTPException(status_code=401, detail="Bearer token has expired")
        if iat > now:
            raise HTTPException(status_code=401, detail="Bearer token was issued in the future")
        if exp - iat > ttl_seconds:
            raise HTTPException(status_code=401, detail="Bearer token lifetime exceeds 24 hours")
        if "iat" not in payload and exp - now > ttl_seconds:
            raise HTTPException(status_code=401, detail="Bearer token lifetime exceeds 24 hours")
        if payload.get("nbf") is not None and float(payload["nbf"]) > now:
            raise HTTPException(status_code=401, detail="Bearer token is not active yet")
    except KeyError as exc:
        raise HTTPException(status_code=401, detail="Bearer token must include exp") from exc
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=401, detail="Invalid bearer token time claims") from exc
    return payload


def create_site_jwt(email: str, site_id: str, role: SiteRole, secret: str, ttl_hours: int = 24) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "email": email,
        "site_id": site_id,
        "role": role,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=ttl_hours)).timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    signing_input = f"{_encode_segment(header)}.{_encode_segment(payload)}"
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).rstrip(b"=").decode("ascii")
    return f"{signing_input}.{encoded_signature}"


def current_principal(credentials: HTTPAuthorizationCredentials | None = Depends(security)) -> SitePrincipal:
    settings = get_settings()
    if not settings.jwt_secret:
        raise HTTPException(status_code=503, detail="JWT_SECRET is not configured")
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer token is required")

    payload = _verify_hs256_jwt(credentials.credentials, settings.jwt_secret)
    email = payload.get("email")
    site_id = payload.get("site_id")
    role = payload.get("role")
    if not isinstance(email, str) or not isinstance(site_id, str) or role not in {"site_admin", "publisher", "reader"}:
        raise HTTPException(status_code=401, detail="JWT must contain email, site_id and valid role")

    domains = settings.allowed_site_adapter_email_domains
    email_domain = email.rsplit("@", 1)[-1].lower() if "@" in email else ""
    if domains and email_domain not in domains:
        raise HTTPException(status_code=403, detail="Email domain is not allowed")
    with SessionLocal() as session:
        user = session.query(AuthUser).filter(AuthUser.email == email.lower()).first()
        if user is None or not user.enabled:
            raise HTTPException(status_code=401, detail="Token user is not active")
    return SitePrincipal(email=email, site_id=site_id, role=role)


def require_roles(*roles: SiteRole):
    def dependency(principal: SitePrincipal = Depends(current_principal)) -> SitePrincipal:
        if principal.role not in roles:
            raise HTTPException(status_code=403, detail="Insufficient role for this operation")
        return principal

    return dependency


def require_same_site(principal: SitePrincipal, site_id: str) -> None:
    if principal.site_id != site_id:
        raise HTTPException(status_code=403, detail="JWT site_id does not match requested site_id")
