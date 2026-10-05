from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request

from app.agent import AgentClient
from app.client import TelegramClient
from app.config import get_settings
from app.logging import audit_event, close_logging, configure_logging
from app.routes import router

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(
        settings.log_level,
        settings.telegram_bot_token,
        settings.log_directory,
        settings.audit_log_raw_content,
    )

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
    close_logging()


app = FastAPI(title="Perry Telegram Connector", lifespan=lifespan)
app.include_router(router)


@app.middleware("http")
async def request_audit_middleware(request: Request, call_next):
    request_id = str(uuid4())
    started = time.perf_counter()
    audit_event(
        "http.request.started",
        raw_content=get_settings().audit_log_raw_content,
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        query=str(request.url.query),
        client=str(request.client.host if request.client else None),
        headers=dict(request.headers),
    )
    try:
        response = await call_next(request)
    except Exception as exc:
        audit_event(
            "http.request.failed",
            raw_content=get_settings().audit_log_raw_content,
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
            exception_type=type(exc).__name__,
            exception=str(exc),
        )
        raise
    audit_event(
        "http.request.completed",
        raw_content=get_settings().audit_log_raw_content,
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 2),
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.get("/health")
async def health():
    return {"status": "ok"}