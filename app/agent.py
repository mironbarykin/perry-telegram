from __future__ import annotations

import logging

import httpx

from app.config import Settings
from app.schema import AgentRequest, AgentResponse

logger = logging.getLogger(__name__)


class AgentClient:
    """Talks to the LLM (RAG) Agent Engine that actually understands messages."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._http = http or httpx.AsyncClient(timeout=settings.agent_timeout_seconds)

    async def ask(
        self,
        user_id: str,
        text: str,
    ) -> AgentResponse:
        request = AgentRequest(telegram_id=user_id, message=text)

        resp = await self._http.post(
            self._settings.agent_api_url,
            json=request.model_dump(),
            headers={"X-API-Key": f"{self._settings.agent_api_key}"},
        )
        resp.raise_for_status()
        return AgentResponse.model_validate(resp.json())

    async def aclose(self) -> None:
        await self._http.aclose()