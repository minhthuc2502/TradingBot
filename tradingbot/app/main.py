"""Application entry point.

Wires FastAPI, the DB, and the APScheduler scheduler together using the
new ``lifespan`` context manager (FastAPI ≥ 0.93).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.webhook import router as webhook_router
from app.config import settings
from app.db.session import init_db
from app.services.discord_service import start_discord_bot, stop_discord_bot
from app.services.scheduler import start_scheduler, stop_scheduler

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting %s …", settings.app_name)

    os.makedirs("data", exist_ok=True)
    init_db()
    logger.info("Database ready")

    start_scheduler()
    await start_discord_bot()

    yield  # application runs here

    await stop_discord_bot()
    stop_scheduler()
    logger.info("%s stopped", settings.app_name)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="AI-powered stock trading bot with WhatsApp notifications.",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs" if settings.debug else None,
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["POST", "GET"],
        allow_headers=["*"],
    )

    app.include_router(webhook_router)

    @app.get("/health", tags=["monitoring"])
    async def health_check() -> dict:
        return {"status": "ok", "service": settings.app_name}

    return app


app = create_app()


# ---------------------------------------------------------------------------
# Dev server entry point:  python -m app.main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )
