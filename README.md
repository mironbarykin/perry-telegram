## Perry Telegram

Perry Telegram is a small FastAPI connector between Telegram and the Perry agent engine. It receives Telegram webhook updates, forwards messages to the engine, sends replies back to Telegram, and supports inline approval or decline actions for pending confirmations.

### Setup

1. Copy `.env.example` to `.env` and fill in the required credentials.
2. Install dependencies with `poetry install`.
3. Start the service:

```bash
poetry run uvicorn app.main:app --reload
```

The health check is available at `/health`. Set `PUBLIC_BASE_URL` when the service is publicly reachable so the Telegram webhook is registered automatically.
