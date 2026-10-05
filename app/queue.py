from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MessageBatch:
    chat_id: int
    user_id: str
    texts: tuple[str, ...]


MessageHandler = Callable[[MessageBatch], Awaitable[None]]


class ChatMessageQueue:
    """Debounce and serialize ordinary messages independently per chat."""

    def __init__(self, debounce_seconds: float, handler: MessageHandler) -> None:
        self._debounce_seconds = debounce_seconds
        self._handler = handler
        self._queues: dict[int, asyncio.Queue[tuple[str, str]]] = {}
        self._workers: dict[int, asyncio.Task[None]] = {}
        self._stopping = False

    async def enqueue(self, chat_id: int, user_id: str, text: str) -> None:
        if self._stopping:
            raise RuntimeError("message queue is stopping")
        queue = self._queues.get(chat_id)
        if queue is None:
            queue = self._queues[chat_id] = asyncio.Queue()
            self._workers[chat_id] = asyncio.create_task(
                self._run_chat(chat_id, queue),
                name=f"telegram-chat-{chat_id}",
            )
        await queue.put((user_id, text))

    async def shutdown(self) -> None:
        self._stopping = True
        workers = list(self._workers.values())
        for worker in workers:
            worker.cancel()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        self._workers.clear()
        self._queues.clear()

    async def _run_chat(
        self,
        chat_id: int,
        queue: asyncio.Queue[tuple[str, str]],
    ) -> None:
        try:
            while True:
                user_id, text = await queue.get()
                texts = [text]
                await asyncio.sleep(self._debounce_seconds)
                while not queue.empty():
                    user_id, text = queue.get_nowait()
                    texts.append(text)

                await self._handler(
                    MessageBatch(chat_id=chat_id, user_id=user_id, texts=tuple(texts))
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("message queue worker failed for chat %s", chat_id)
        finally:
            self._queues.pop(chat_id, None)
            self._workers.pop(chat_id, None)
