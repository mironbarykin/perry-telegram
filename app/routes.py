from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status

from app.client import TelegramClient
from app.config import Settings, get_settings
from app.agent import AgentClient
from app.schema import SendRequest, SendResponse, TelegramUpdate

logger = logging.getLogger(__name__)
router = APIRouter()


def get_telegram_client(request: Request) -> TelegramClient:
    return request.app.state.telegram_client


def get_agent_client(request: Request) -> AgentClient:
    return request.app.state.agent_client


@router.post("/webhook/telegram", status_code=status.HTTP_200_OK)
async def telegram_webhook(
    update: TelegramUpdate,
    x_telegram_bot_api_secret_token: str | None = Header(default=None),
    settings: Settings = Depends(get_settings),
    telegram: TelegramClient = Depends(get_telegram_client),
    agent: AgentClient = Depends(get_agent_client),
):
    if x_telegram_bot_api_secret_token != settings.telegram_webhook_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="bad secret token")

    callback = update.callback_query
    if callback is not None:
        await telegram.answer_callback_query(callback.id)
        if callback.message is None or not callback.data:
            return {"ok": True}

        action, separator, confirmation_id = callback.data.partition(":")
        if separator != ":" or action not in {"confirm", "decline"} or not confirmation_id:
            return {"ok": True}

        await telegram.clear_inline_keyboard(
            chat_id=callback.message.chat.id,
            message_id=callback.message.message_id,
        )

        if action == "confirm":
            try:
                result = await telegram.confirm_action(
                    confirmation_id=confirmation_id,
                    user_telegram_id=callback.from_.id,
                )
                reply = result.get("message", "Action confirmed.")
            except Exception:
                logger.exception("confirmation engine call failed")
                reply = "I could not confirm that action. Please try again."
            await telegram.send_message(chat_id=callback.message.chat.id, text=reply)
        else:
            await telegram.decline_action(
                confirmation_id=confirmation_id,
                user_telegram_id=callback.from_.id,
            )
            await telegram.send_message(chat_id=callback.message.chat.id, text="Action declined.")
        return {"ok": True}

    message = update.message or update.edited_message
    if message is None or message.text is None:
        return {"ok": True}

    user_id = str(message.from_.id) if message.from_ else str(message.chat.id)
    await telegram.send_chat_action(chat_id=message.chat.id)
    placeholder = await telegram.send_message(chat_id=message.chat.id, text="Thinking...")
    placeholder_message_id = (placeholder.get("result") or {}).get("message_id")

    try:
        agent_response = await agent.ask(
            user_id=user_id,
            text=message.text,
        )
    except Exception:
        logger.exception("agent engine call failed")
        reply = "Hi, I\'m busy rn. Please try again later ;)"
        if placeholder_message_id is not None:
            await telegram.edit_message_text(
                chat_id=message.chat.id,
                message_id=placeholder_message_id,
                text=reply,
            )
        else:
            await telegram.send_message(chat_id=message.chat.id, text=reply)
        return {"ok": True}

    keyboard = []
    for confirmation in agent_response.pending_confirmations:
        keyboard.append(
            [
                {"text": "Approve", "callback_data": f"confirm:{confirmation.id}"},
                {"text": "Decline", "callback_data": f"decline:{confirmation.id}"},
            ]
        )

    reply_markup = {"inline_keyboard": keyboard} if keyboard else None
    if placeholder_message_id is not None:
        await telegram.edit_message_text(
            chat_id=message.chat.id,
            message_id=placeholder_message_id,
            text=agent_response.reply,
            reply_markup=reply_markup,
        )
    else:
        await telegram.send_message(
            chat_id=message.chat.id,
            text=agent_response.reply,
            reply_markup=reply_markup,
        )
    return {"ok": True}


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