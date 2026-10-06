from __future__ import annotations

import logging
import time

import httpx

from app.config import Settings
from app.logging import audit_event
from app.schema import (
    AgentRequest,
    AgentResponse,
    CalendarAuthorizationRequest,
    CalendarAuthorizationResponse,
    ConfirmationRequest,
    TelegramWelcomeRequest,
)

logger = logging.getLogger(__name__)


class AgentClient:
    """Talks to the LLM (RAG) Agent Engine that actually understands messages."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(
                settings.agent_timeout_seconds,
                connect=10.0,
            )
        )

    async def ask(
        self,
        user_id: str,
        text: str,
    ) -> AgentResponse:
        try:
            telegram_id = int(user_id)
        except ValueError as exc:
            raise ValueError(f"Invalid Telegram user ID: {user_id}") from exc
        request = AgentRequest(
            telegram_id=telegram_id,
            message=text,
            extended_confirmations=True,
        )

        payload = request.model_dump()
        started = time.perf_counter()
        resp = await self._http.post(
            self._settings.agent_api_url + '/chat',
            json=payload,
            headers={"X-API-Key": f"{self._settings.agent_api_key}"},
        )
        audit_event(
            "agent.api.request",
            operation="chat",
            payload=payload,
            status_code=resp.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        resp.raise_for_status()
        return AgentResponse.model_validate(resp.json())

    async def authorize_google_calendar(
        self,
        telegram_id: int,
    ) -> CalendarAuthorizationResponse:
        request = CalendarAuthorizationRequest(telegram_id=telegram_id)

        payload = request.model_dump()
        started = time.perf_counter()
        resp = await self._http.post(
            f"{self._settings.agent_api_url.rstrip('/')}/integrations/google/calendar/authorize",
            json=payload,
            headers={"X-API-Key": self._settings.agent_api_key},
        )
        audit_event(
            "agent.api.request",
            operation="authorize_google_calendar",
            payload=payload,
            status_code=resp.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        resp.raise_for_status()
        return CalendarAuthorizationResponse.model_validate(resp.json())

    async def register_telegram_welcome(
        self,
        request: TelegramWelcomeRequest,
    ) -> dict[str, object]:
        payload = request.model_dump()
        started = time.perf_counter()
        resp = await self._http.post(
            f"{self._settings.agent_api_url.rstrip('/')}/integrations/telegram/welcome",
            json=payload,
            headers={"X-API-Key": self._settings.agent_api_key},
        )
        audit_event(
            "agent.api.request",
            operation="register_telegram_welcome",
            payload=payload,
            status_code=resp.status_code,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        resp.raise_for_status()
        result = resp.json()
        if not isinstance(result, dict):
            raise ValueError("Telegram welcome endpoint returned an invalid response")
        logger.info(
            "Telegram welcome registered user %s with status=%s notification=%s",
            payload["telegram_id"],
            result.get("status"),
            result.get("notification", "not_applicable"),
        )
        return result

    async def confirm_actions(
        self,
        confirmation_ids: list[str],
        telegram_id: int,
    ) -> None:
        request = ConfirmationRequest(telegram_id=telegram_id)
        
        for confirmation in confirmation_ids:
            started = time.perf_counter()
            resp = await self._http.post(
                f"{self._settings.agent_api_url.rstrip('/')}/confirmations/{confirmation}",
                json=request.model_dump(),
                headers={"X-API-Key": self._settings.agent_api_key},
            )
            audit_event(
                "agent.api.request",
                operation="confirm_action",
                confirmation_id=confirmation,
                telegram_id=telegram_id,
                status_code=resp.status_code,
                duration_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            resp.raise_for_status()


    async def aclose(self) -> None:
        await self._http.aclose()