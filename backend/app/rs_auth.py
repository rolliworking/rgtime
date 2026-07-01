"""RS / consumer-app auth — shared-secret Bearer, fail-closed."""

from __future__ import annotations

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

_bearer = HTTPBearer(auto_error=False)


async def require_rs_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> None:
    settings = get_settings()
    token = settings.rgtime_to_rs_token
    if not token:
        raise HTTPException(status_code=503, detail="RS integration auth not configured")
    if credentials is None or credentials.credentials != token:
        raise HTTPException(status_code=401, detail="Unauthorized")
