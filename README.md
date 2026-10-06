## Perry Telegram

Perry Telegram is a small FastAPI connector between Telegram and the Perry agent engine. It receives Telegram webhook updates, forwards messages to the engine, sends replies back to Telegram, and supports inline approval or decline actions for pending confirmations.

When an agent response contains multiple pending confirmations, the final reply
message includes a **Confirm all** button that approves every action in that
response.

Individual confirmation prompts are sent silently so they do not generate an
additional Telegram notification. Each prompt includes the action details
provided by Perry Engine when available.

Messages sent in a quick burst are debounced for 500 ms, combined in order, and
processed sequentially per chat so Perry keeps one coherent context. While Perry
is working, the placeholder rotates through short status phrases every 5 seconds
with a `⌛` prefix, then changes to `⏳` before the final response is displayed.
Final responses include the elapsed thinking time, such as `(12s)`.

On a user's first text message, the connector registers the Telegram identity
with Perry Engine through `/integrations/telegram/welcome`. The engine records
the contact as pending and sends Miron a natural-language question containing
the person's display name and Telegram ID. Miron replies in his normal Perry
conversation with what he knows; the engine then lets the LLM call its contact
access proposal tool. The connector renders the resulting confirmation with
the normal inline approval UI. Until the contact is approved, the engine does
not execute agent tools for that Telegram user.

### Parent interface

Set `TELEGRAM_PARENT_IDS` to a comma-separated list of Telegram user IDs.
Parents can then send `/update` to install the persistent parent reply
keyboard. The visible button text is not sent to the agent as the instruction;
each button maps to a predefined internal prompt. The shopping button asks for
one shopping-list message and then prepares separate task proposals for its
items.

### Setup

1. Copy `.env.example` to `.env` and fill in the required credentials.
2. Install dependencies with `poetry install`.
3. Start the service:

```bash
poetry run uvicorn app.main:app --reload
```

The health check is available at `/health`. Set `PUBLIC_BASE_URL` when the service is publicly reachable so the Telegram webhook is registered automatically.

`TELEGRAM_MESSAGE_DEBOUNCE_SECONDS` and `TELEGRAM_THINKING_ROTATION_SECONDS`
can be set to adjust the queue debounce and status rotation intervals.

### Connect Google Calendar

Send `/connect-calendar` to the Telegram bot. The connector asks Perry Engine
to create a user-scoped Google OAuth consent URL and sends that URL back to the
user. Google redirects to the callback configured on Perry Engine; the Telegram
connector does not proxy the callback.
