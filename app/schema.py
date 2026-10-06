from __future__ import annotations

from pydantic import BaseModel, Field


class TelegramChat(BaseModel):
    id: int
    type: str


class TelegramUser(BaseModel):
    id: int
    is_bot: bool = False
    first_name: str | None = None
    username: str | None = None
    language_code: str | None = None


class TelegramMessage(BaseModel):
    message_id: int
    date: int
    chat: TelegramChat
    from_: TelegramUser | None = Field(None, alias="from")
    text: str | None = None

    model_config = {"populate_by_name": True}


class TelegramUpdate(BaseModel):
    update_id: int
    message: TelegramMessage | None = None
    edited_message: TelegramMessage | None = None
    callback_query: "TelegramCallbackQuery | None" = None


class TelegramCallbackQuery(BaseModel):
    id: str
    from_: TelegramUser = Field(alias="from")
    message: TelegramMessage | None = None
    data: str | None = None

    model_config = {"populate_by_name": True}


class AgentRequest(BaseModel):
    telegram_id: str
    message: str
    extended_confirmations: bool = True


class CalendarAuthorizationRequest(BaseModel):
    telegram_id: int = Field(gt=0)


class CalendarAuthorizationResponse(BaseModel):
    authorization_url: str = Field(min_length=1)


class AgentResponse(BaseModel):
    reply: str
    pending_confirmations: list["PendingConfirmation"] = Field(default_factory=list)


class PendingConfirmation(BaseModel):
    id: str
    action_type: str | None = None
    expires_in_minutes: int | None = None
    details: dict[str, object] | None = None

class ConfirmationRequest(BaseModel):
    telegram_id: int = Field(gt=0)

class SendRequest(BaseModel):
    chat_id: int
    text: str
    parse_mode: str | None = None


class SendResponse(BaseModel):
    ok: bool
    telegram_message_id: int | None = None
