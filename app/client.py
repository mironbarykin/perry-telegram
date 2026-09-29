from __future__ import annotations

import logging
from urllib.parse import quote

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class TelegramClient:
    """Thin async wrapper around the Telegram Bot API — plain HTTP, no heavy SDK."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient | None = None) -> None:
        self._settings = settings
        self._base = f"{settings.telegram_api_base}/bot{settings.telegram_bot_token}"
        self._http = http or httpx.AsyncClient(timeout=15.0)

    async def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str | None = None,
        reply_markup: dict | None = None,
    ) -> dict:
        payload: dict = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup

        resp = await self._http.post(f"{self._base}/sendMessage", json=payload)
        self._raise_for_status(resp, "sendMessage")
        return self._api_result(resp, "sendMessage")

    async def send_chat_action(self, chat_id: int, action: str = "typing") -> dict:
        resp = await self._http.post(
            f"{self._base}/sendChatAction",
            json={"chat_id": chat_id, "action": action},
        )
        self._raise_for_status(resp, "sendChatAction")
        return self._api_result(resp, "sendChatAction")

    async def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict | None = None,
        parse_mode: str | None = None,
    ) -> dict:
        payload: dict = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if parse_mode:
            payload["parse_mode"] = parse_mode

        resp = await self._http.post(f"{self._base}/editMessageText", json=payload)
        self._raise_for_status(resp, "editMessageText")
        return self._api_result(resp, "editMessageText")

    async def confirm_action(
        self,
        confirmation_id: str,
        user_telegram_id: int,
    ) -> dict:
        url = (
            f"{self._settings.agent_api_url.rstrip('/')}/confirmations/"
            f"{quote(confirmation_id, safe='')}"
        )
        resp = await self._http.post(
            url,
            json={"telegram_id": user_telegram_id},
            headers={"X-API-Key": f"{self._settings.agent_api_key}"},
        )
        self._raise_for_status(resp, "confirmAction")
        return self._api_result(resp, "confirmAction")

    async def answer_callback_query(self, callback_query_id: str) -> dict:
        resp = await self._http.post(
            f"{self._base}/answerCallbackQuery",
            json={"callback_query_id": callback_query_id},
        )
        self._raise_for_status(resp, "answerCallbackQuery")
        return self._api_result(resp, "answerCallbackQuery")

    async def clear_inline_keyboard(self, chat_id: int, message_id: int) -> dict:
        resp = await self._http.post(
            f"{self._base}/editMessageReplyMarkup",
            json={
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": []},
            },
        )
        self._raise_for_status(resp, "editMessageReplyMarkup")
        return self._api_result(resp, "editMessageReplyMarkup")

    async def decline_action(
        self,
        confirmation_id: str,
        user_telegram_id: int,
    ) -> None:
        # TODO: call the engine once decline semantics are available:
        # await self._http.delete(
        #     f"{self._settings.agent_api_url.rstrip('/')}/confirmations/"
        #     f"{quote(confirmation_id, safe='')}",
        #     headers={"X-API-Key": f"{self._settings.agent_api_key}"},
        # )
        return None

    async def set_webhook(self, url: str) -> dict:
        resp = await self._http.post(
            f"{self._base}/setWebhook",
            json={"url": url, "secret_token": self._settings.telegram_webhook_secret},
        )
        self._raise_for_status(resp, "setWebhook")
        return self._api_result(resp, "setWebhook")

    async def delete_webhook(self) -> dict:
        resp = await self._http.post(f"{self._base}/deleteWebhook")
        self._raise_for_status(resp, "deleteWebhook")
        return self._api_result(resp, "deleteWebhook")

    @staticmethod
    def _raise_for_status(resp: httpx.Response, operation: str) -> None:
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError:
            try:
                detail = resp.json().get("description", resp.text)
            except ValueError:
                detail = resp.text
            logger.error(
                "Telegram %s returned HTTP %s: %s",
                operation,
                resp.status_code,
                detail,
            )
            raise

    @staticmethod
    def _api_result(resp: httpx.Response, operation: str) -> dict:
        data = resp.json()
        if not data.get("ok"):
            description = data.get("description", "unknown Telegram API error")
            logger.error("Telegram %s failed: %s", operation, description)
            raise RuntimeError(f"Telegram {operation} failed: {description}")
        return data

    async def aclose(self) -> None:
        await self._http.aclose()
