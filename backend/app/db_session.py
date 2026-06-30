from collections.abc import AsyncGenerator
from typing import Any

import asyncpg
from fastapi import Request


async def get_db(request: Request) -> AsyncGenerator[asyncpg.Connection, None]:
    pool: asyncpg.Pool = request.app.state.db_pool
    async with pool.acquire() as connection:
        yield connection
