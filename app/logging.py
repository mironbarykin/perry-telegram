from __future__ import annotations

import logging
import re


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


def configure_logging(level: str, telegram_token: str) -> None:
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
