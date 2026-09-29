from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.agent import AgentClient
from app.client import TelegramClient
from app.config import get_settings
from app.logging import configure_logging
from app.routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.telegram_bot_token)

    app.state.telegram_client = TelegramClient(settings)
    app.state.agent_client = AgentClient(settings)

    if settings.public_base_url:
        webhook_url = f"{settings.public_base_url.rstrip('/')}/webhook/telegram"
        try:
            await app.state.telegram_client.set_webhook(webhook_url)
            logger.info("Telegram webhook set to %s", webhook_url)
        except Exception:
            logger.exception("failed to register telegram webhook on startup")

    yield

    await app.state.telegram_client.aclose()
    await app.state.agent_client.aclose()


app = FastAPI(title="Perry Telegram Connector", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
async def health():
    return {"status": "ok"}