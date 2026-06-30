from typing import Annotated

import asyncpg
from fastapi import Depends, Request

from app.database import get_db

DbConn = Annotated[asyncpg.Connection, Depends(get_db)]


def get_actor_type(request: Request) -> str:
    """Derive actor type from request headers (kiosk vs admin)."""
    client = request.headers.get("X-RGTime-Client", "admin")
    if client == "kiosk":
        return "kiosk"
    if client == "system":
        return "system"
    return "admin"
