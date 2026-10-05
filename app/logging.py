from __future__ import annotations

import logging
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_raw_content_enabled = True


class RedactingFormatter(logging.Formatter):
    """Remove Telegram bot tokens from messages and exception tracebacks."""

    _bot_token_pattern = re.compile(r"(/bot)(\d+:[A-Za-z0-9_-]+)")

    def __init__(self, token: str, fmt: str | None = None) -> None:
        super().__init__(fmt)
        self._token_pattern = re.compile(re.escape(token)) if token else None

    def format(self, record: logging.LogRecord) -> str:
        rendered = super().format(record)
        rendered = self._bot_token_pattern.sub(r"\1[REDACTED]", rendered)
        if self._token_pattern is not None:
            rendered = self._token_pattern.sub("[REDACTED]", rendered)
        return rendered


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "audit_event", None)
        if event is None:
            event = {"event": "log", "message": record.getMessage()}
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            **event,
        }
        return json.dumps(event, ensure_ascii=True, default=str)


def configure_logging(
    level: str,
    telegram_token: str,
    log_directory: str = "/logs",
    raw_content_enabled: bool = True,
) -> None:
    global _raw_content_enabled
    _raw_content_enabled = raw_content_enabled
    formatter = RedactingFormatter(
        telegram_token,
        "%(levelname)s:%(name)s:%(message)s",
    )
    root = logging.getLogger()
    root.setLevel(level)

    if not root.handlers:
        root.addHandler(logging.StreamHandler())

    for handler in root.handlers:
        handler.setFormatter(formatter)

    for logger_name in ("httpx", "uvicorn", "uvicorn.error", "uvicorn.access"):
        for handler in logging.getLogger(logger_name).handlers:
            handler.setFormatter(formatter)

    audit_logger = logging.getLogger("audit")
    audit_logger.setLevel(logging.INFO)
    audit_logger.propagate = False
    if not audit_logger.handlers:
        try:
            Path(log_directory).mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(
                Path(log_directory) / "audit.jsonl",
                encoding="utf-8",
            )
        except OSError:
            logging.getLogger(__name__).exception(
                "failed to open audit log file in %s", log_directory
            )
        else:
            handler.setFormatter(JsonFormatter())
            audit_logger.addHandler(handler)


def audit_event(
    event: str,
    raw_content: bool | None = None,
    **fields: Any,
) -> None:
    """Write an analysis-friendly event without ever persisting credentials."""
    if raw_content is None:
        raw_content = _raw_content_enabled
    safe_fields = _sanitize(fields, raw_content=raw_content)
    logging.getLogger("audit").info(
        event,
        extra={
            "audit_event": {
                "event": event,
                "event_id": str(uuid4()),
                **safe_fields,
            }
        },
    )


def close_logging() -> None:
    audit_logger = logging.getLogger("audit")
    for handler in audit_logger.handlers[:]:
        handler.close()
        audit_logger.removeHandler(handler)


def _sanitize(value: Any, *, raw_content: bool) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _sanitize(item, raw_content=raw_content)
            for key, item in value.items()
            if str(key).lower() not in {
                "token",
                "secret",
                "api_key",
                "authorization",
                "x-api-key",
                "x-telegram-bot-api-secret-token",
            }
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, raw_content=raw_content) for item in value]
    if isinstance(value, str):
        if raw_content:
            return value
        return f"<redacted:{len(value)} chars>"
    return value
