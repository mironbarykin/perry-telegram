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
