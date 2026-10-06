from __future__ import annotations

import asyncio
from datetime import datetime
import html
import json
import logging
import time
from uuid import uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.client import TelegramClient
from app.config import Settings, get_settings
from app.agent import AgentClient
from app.schema import PendingConfirmation, SendRequest, SendResponse, TelegramUpdate
from app.formatting import markdown_to_telegram_html, split_message
from app.logging import audit_event
from app.queue import ChatMessageQueue, MessageBatch

logger = logging.getLogger(__name__)
router = APIRouter()
_HIDDEN_CONFIRMATION_FIELDS = {
    "id",
    "task_id",
    "tasklist_id",
    "etag",
    "risk",
    "_risk",
    "destination_tasklist_id",
}
THINKING_PHRASES = (
    "⏳Thinking through it...",
    "⌛Connecting the dots...",
    "⏳Checking the details...",
    "⌛Consulting my brain...",
    "⏳Organizing my thoughts...",
    "⌛Looking into the past...",
    "⏳Asking the helpful electrons...",
    "⌛Polishing the answer...",
    "⏳Almost there...",
)

def get_telegram_client(request: Request) -> TelegramClient:
    return request.app.state.telegram_client


def get_agent_client(request: Request) -> AgentClient:
    return request.app.state.agent_client


@router.post("/webhook/telegram", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    update: TelegramUpdate,
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    telegram: TelegramClient = Depends(get_telegram_client),
    agent: AgentClient = Depends(get_agent_client),
):
    audit_event(
        "telegram.update.received",
        raw_content=settings.audit_log_raw_content,
        update=update.model_dump(by_alias=True),
        source_ip=request.client.host if request.client else None,
    )
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        audit_event("telegram.update.rejected", reason="invalid_secret")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad secret token")

    logger.info("received Telegram update %s", update.update_id)
    processed_update_ids = getattr(request.app.state, "processed_update_ids", None)
    if processed_update_ids is None:
        processed_update_ids = request.app.state.processed_update_ids = set()
    if update.update_id in processed_update_ids:
        logger.info("ignoring duplicate Telegram update %s", update.update_id)
        return {"ok": True}
    processed_update_ids.add(update.update_id)
    if len(processed_update_ids) > 10_000:
        processed_update_ids.pop()

    callback = update.callback_query
    if callback is not None:
        audit_event(
            "telegram.callback.clicked",
            raw_content=settings.audit_log_raw_content,
            callback_id=callback.id,
            user=callback.from_.model_dump(by_alias=True),
            data=callback.data,
            message=callback.message.model_dump(by_alias=True) if callback.message else None,
        )
        await telegram.answer_callback_query(callback.id)
        if callback.message is None or not callback.data:
            return {"ok": True}

        action, separator, confirmation_id = callback.data.partition(":")
        if action == "confirm_all":
            confirmation_batches = getattr(request.app.state, "confirmation_batches", {})
            confirmation_ids = confirmation_batches.pop(confirmation_id, None)
            if separator != ":" or not confirmation_id or confirmation_ids is None:
                return {"ok": True}

            current_text = (callback.message.text or "").strip()
            try:
                await agent.confirm_actions(
                    confirmation_ids=confirmation_ids,
                    telegram_id=callback.from_.id,
                )
            except Exception:
                logger.exception("confirm all engine call failed")
                edited_text = f"(Confirmation failed) {current_text or 'Confirmation request'}"
            else:
                edited_text = f"(All confirmed) {current_text or 'Confirmation request'}"

            await telegram.edit_message_text(
                chat_id=callback.message.chat.id,
                message_id=callback.message.message_id,
                text=edited_text,
                reply_markup={"inline_keyboard": []},
            )
            return {"ok": True}

        if separator != ":" or action not in {"confirm", "decline"} or not confirmation_id:
            return {"ok": True}

        confirmation_status = "A" if action == "confirm" else "D"
        current_text = (callback.message.text or "").strip()
        confirmation_text = current_text or confirmation_id
        edited_text = f"({confirmation_status}) {confirmation_text}"

        if action == "confirm":
            try:
                await telegram.confirm_action(
                    confirmation_id=confirmation_id,
                    user_telegram_id=callback.from_.id,
                )
            except Exception:
                logger.exception("confirmation engine call failed")
        else:
            await telegram.decline_action(
                confirmation_id=confirmation_id,
                user_telegram_id=callback.from_.id,
            )

        await telegram.edit_message_text(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
            text=edited_text,
            reply_markup={"inline_keyboard": []},
        )
        return {"ok": True}

    message = update.message or update.edited_message
    if message is None or message.text is None:
        return await telegram.send_message(
            chat_id=message.chat.id if message else 0,
            text="I can only process text messages for now.",
        )

    user_id = str(message.from_.id) if message.from_ else str(message.chat.id)
    audit_event(
        "telegram.message.received",
        raw_content=settings.audit_log_raw_content,
        update_id=update.update_id,
        user_id=user_id,
        chat=message.chat.model_dump(),
        user=message.from_.model_dump(by_alias=True) if message.from_ else None,
        message_id=message.message_id,
        text=message.text,
    )
    command = message.text.split(maxsplit=1)[0].lower()
    if command == "/connect-calendar" or command.startswith("/connect"):
        telegram_id = message.from_.id if message.from_ else message.chat.id
        try:
            authorization = await agent.authorize_google_calendar(telegram_id)
        except httpx.HTTPStatusError as exc:
            detail = _engine_error_detail(exc)
            logger.error("google calendar authorization rejected: %s", detail)
            await telegram.send_message(
                chat_id=message.chat.id,
                text=f"Google Calendar connection failed: {detail}",
            )
            return {"ok": True}
        except Exception:
            logger.exception("google calendar authorization request failed")
            await telegram.send_message(
                chat_id=message.chat.id,
                text="I could not start Google Calendar connection. Please try again later.",
            )
            return {"ok": True}

        await telegram.send_message(
            chat_id=message.chat.id,
            text=(
                "Open this link to connect Google Calendar:\n"
                f"{authorization.authorization_url}"
            ),
        )
        return {"ok": True}

    if command.startswith('/'):
        await telegram.send_message(
            chat_id=message.chat.id,
            text="I don't recognize that command. Please contact Miron for infos ;).",
        )
        return {"ok": True}

    confirmation_batches = getattr(request.app.state, "confirmation_batches", None)
    if confirmation_batches is None:
        confirmation_batches = request.app.state.confirmation_batches = {}
    queue: ChatMessageQueue = request.app.state.message_queue
    await queue.enqueue(message.chat.id, user_id, message.text)
    logger.info(
        "queued agent request for Telegram update %s (chat %s)",
        update.update_id,
        message.chat.id,
    )
    return {"ok": True}


async def process_message_batch(
    telegram: TelegramClient,
    agent: AgentClient,
    confirmation_batches: dict[str, list[str]],
    batch: MessageBatch,
    thinking_rotation_seconds: float,
) -> None:
    chat_id = batch.chat_id
    text = "\n".join(batch.texts)
    thinking_started = time.perf_counter()
    placeholder = await telegram.send_message(
        chat_id=chat_id, text=THINKING_PHRASES[0]
    )
    placeholder_message_id = (placeholder.get("result") or {}).get("message_id")
    thinking_task = asyncio.create_task(
        _rotate_thinking_status(
            telegram, chat_id, placeholder_message_id, thinking_rotation_seconds
        )
    )
    logger.info("starting agent request for chat %s", chat_id)
    try:
        agent_response = await agent.ask(user_id=batch.user_id, text=text)
        reply = agent_response.reply
        logger.info(
            "agent request completed for chat %s (%d reply characters, %d confirmations)",
            chat_id,
            len(reply),
            len(agent_response.pending_confirmations),
        )
    except Exception as exc:
        logger.exception("agent engine call failed (%s: %s)", type(exc).__name__, exc)
        reply = "Hi, I'm busy rn. Please try again later ;)"
        agent_response = None

    reply = f"({max(1, round(time.perf_counter() - thinking_started))}s)\n{reply}"

    reply_markup = None
    if agent_response is not None and agent_response.pending_confirmations:
        confirmation_token = uuid4().hex
        confirmation_batches[confirmation_token] = [
            confirmation.id for confirmation in agent_response.pending_confirmations
        ]
        reply_markup = {
            "inline_keyboard": [
                [
                    {
                        "text": "Confirm all",
                        "callback_data": f"confirm_all:{confirmation_token}",
                    }
                ]
            ]
        }

    try:
        thinking_task.cancel()
        await asyncio.gather(thinking_task, return_exceptions=True)
        if placeholder_message_id is not None:
            try:
                await telegram.edit_message_text(
                    chat_id=chat_id,
                    message_id=placeholder_message_id,
                    text=f"{THINKING_PHRASES[0][2:]}",
                )
            except Exception:
                logger.exception("failed to mark thinking status for chat %s", chat_id)
        reply_chunks = split_message(reply)
        if placeholder_message_id is not None:
            try:
                await _edit_formatted_message(
                    telegram,
                    chat_id=chat_id,
                    message_id=placeholder_message_id,
                    markdown=reply_chunks[0],
                    reply_markup=reply_markup if len(reply_chunks) == 1 else None,
                )
                chunks_to_send = reply_chunks[1:]
                logger.info("edited Thinking message for chat %s", chat_id)
            except Exception:
                logger.exception(
                    "failed to edit Thinking message for chat %s; sending a new plain-text reply",
                    chat_id,
                )
                await telegram.send_message(
                    chat_id=chat_id,
                    text=reply_chunks[0],
                    reply_markup=reply_markup if len(reply_chunks) == 1 else None,
                )
                chunks_to_send = reply_chunks[1:]
            for index, chunk in enumerate(chunks_to_send):
                await _send_formatted_message(
                    telegram,
                    chat_id=chat_id,
                    markdown=chunk,
                    reply_markup=reply_markup if index == len(chunks_to_send) - 1 else None,
                )
        else:
            for index, chunk in enumerate(reply_chunks):
                await _send_formatted_message(
                    telegram,
                    chat_id=chat_id,
                    markdown=chunk,
                    reply_markup=reply_markup if index == len(reply_chunks) - 1 else None,
                )
        logger.info("delivered agent response for chat %s", chat_id)

        if agent_response is None:
            return

        for confirmation in agent_response.pending_confirmations:
            details = _format_confirmation_details(confirmation)
            await telegram.send_message(
                chat_id=chat_id,
                text=details or "Confirmation request",
                parse_mode="HTML",
                disable_notification=True,
                reply_markup={
                    "inline_keyboard": [
                        [
                            {
                                "text": "Approve",
                                "callback_data": f"confirm:{confirmation.id}",
                            },
                            {
                                "text": "Decline",
                                "callback_data": f"decline:{confirmation.id}",
                            },
                        ]
                    ]
                },
            )
    except Exception:
        logger.exception("failed to deliver agent response to Telegram for chat %s", chat_id)


def _format_confirmation_details(confirmation: PendingConfirmation) -> str:
    heading = _confirmation_field_label(
        confirmation.action_type or "Confirmation request"
    )
    if not confirmation.details:
        return f"<b>{html.escape(heading)}</b>"

    visible_details = {
        key: value
        for key, value in confirmation.details.items()
        if key not in _HIDDEN_CONFIRMATION_FIELDS
    }
    if not visible_details:
        return f"<b>{html.escape(heading)}</b>"

    detail_lines = ["<b>What will change?</b>"]
    changes = visible_details.pop("changes", None)
    if isinstance(changes, dict) and changes:
        detail_lines.extend(_format_change_lines(changes))
    elif "_preview" in visible_details:
        detail_lines.append(
            f"• {html.escape(_format_confirmation_value(visible_details['_preview']))}"
        )
    else:
        for key, value in sorted(visible_details.items()):
            detail_lines.append(
                f"• <b>{html.escape(_confirmation_field_label(key))}:</b> "
                f"{html.escape(_format_confirmation_value(value, key))}"
            )

    return f"<b>{html.escape(heading)}</b>\n" + "\n".join(detail_lines)


def _format_change_lines(changes: dict[str, object]) -> list[str]:
    visible_changes = {
        key: value
        for key, value in changes.items()
        if key not in {"calendar_id", "event_id"}
    }
    event = visible_changes.pop("event", None)
    if isinstance(event, dict):
        event_fields = event
    elif {"description", "end", "start", "summary"} & visible_changes.keys():
        event_fields = visible_changes
        visible_changes = {}
    else:
        event_fields = {}

    lines: list[str] = []
    if event_fields:
        lines.append("<b>Event</b>")
        preferred_order = ("description", "end", "start", "summary")
        ordered_keys = [
            *[key for key in preferred_order if key in event_fields],
            *sorted(key for key in event_fields if key not in preferred_order),
        ]
        for key in ordered_keys:
            lines.append(
                f"• <b>{html.escape(_confirmation_field_label(key))}:</b> "
                f"{html.escape(_format_confirmation_value(event_fields[key], key))}"
            )

    for key, value in sorted(visible_changes.items()):
        lines.append(
            f"• <b>{html.escape(_confirmation_field_label(key))}:</b> "
            f"{html.escape(_format_confirmation_value(value, key))}"
        )
    return lines


def _format_confirmation_value(value: object, key: str | None = None) -> str:
    if key in {"start", "end"} and isinstance(value, dict):
        date_value = value.get("dateTime") or value.get("date")
        if isinstance(date_value, str):
            return _format_event_datetime(date_value)
    if key == "due":
        date_value = value
        if isinstance(value, dict):
            date_value = value.get("dateTime") or value.get("date")
        if isinstance(date_value, str):
            return _format_event_datetime(date_value)
    if isinstance(value, str):
        return value
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
    except (TypeError, ValueError):
        return str(value)


def _format_event_datetime(value: str, *, date_only: bool = False) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return value
    if date_only or "T" not in value or (
        parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0
    ):
        return f"{parsed.strftime('%a')}, {parsed.day} {parsed.strftime('%b %Y')}"
    return f"{parsed.strftime('%a')}, {parsed.day} {parsed.strftime('%b %Y')} at {parsed.hour:02d}:{parsed.minute:02d}"


def _confirmation_field_label(key: str) -> str:
    return key.lstrip("_").replace("_", " ").capitalize()


async def _rotate_thinking_status(
    telegram: TelegramClient,
    chat_id: int,
    message_id: int | None,
    interval_seconds: float,
) -> None:
    if message_id is None:
        return
    index = 0
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            index = (index + 1) % len(THINKING_PHRASES)
            await telegram.edit_message_text(
                chat_id=chat_id,
                message_id=message_id,
                text=f"{THINKING_PHRASES[index]}",
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("failed to rotate thinking status for chat %s", chat_id)


async def _edit_formatted_message(
    telegram: TelegramClient,
    *,
    chat_id: int,
    message_id: int,
    markdown: str,
    reply_markup: dict | None = None,
) -> None:
    try:
        await telegram.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=markdown_to_telegram_html(markdown),
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except Exception:
        logger.exception(
            "formatted Telegram edit failed for chat %s; retrying as plain text",
            chat_id,
        )
        await telegram.edit_message_text(
            chat_id=chat_id,
            message_id=message_id,
            text=markdown,
            reply_markup=reply_markup,
        )


async def _send_formatted_message(
    telegram: TelegramClient,
    *,
    chat_id: int,
    markdown: str,
    reply_markup: dict | None = None,
) -> None:
    try:
        await telegram.send_message(
            chat_id=chat_id,
            text=markdown_to_telegram_html(markdown),
            parse_mode="HTML",
            reply_markup=reply_markup,
        )
    except Exception:
        logger.exception(
            "formatted Telegram message failed for chat %s; retrying as plain text",
            chat_id,
        )
        await telegram.send_message(
            chat_id=chat_id,
            text=markdown,
            reply_markup=reply_markup,
        )


@router.post("/send", response_model=SendResponse)
async def send_message(
    body: SendRequest,
    x_api_key: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    telegram: TelegramClient = Depends(get_telegram_client),
):
    if x_api_key != settings.outbound_api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid api key")

    result = await telegram.send_message(
        chat_id=body.chat_id, text=body.text, parse_mode=body.parse_mode
    )
    return SendResponse(
        ok=bool(result.get("ok")),
        telegram_message_id=(result.get("result") or {}).get("message_id"),
    )


def _engine_error_detail(error: httpx.HTTPStatusError) -> str:
    try:
        payload = error.response.json()
    except ValueError:
        return f"engine returned HTTP {error.response.status_code}"

    detail = payload.get("detail") if isinstance(payload, dict) else None
    if isinstance(detail, str) and detail:
        return detail
    return f"engine returned HTTP {error.response.status_code}"