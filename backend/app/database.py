from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import config as config_router
from app.routers import health


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=1,
        max_size=10,
        server_settings={"search_path": f"{settings.db_schema},public"},
    )
    app.state.db_pool = pool
    yield
    await pool.close()


def create_app() -> FastAPI:
    from app.routers import kiosk as kiosk_router

    settings = get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router)
    app.include_router(config_router.router, prefix="/api/v1")
    app.include_router(kiosk_router.router, prefix="/api/v1")
    return app
