"""Debounced buffer that batches Telegram events before an agent turn."""

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from src.config import EVENT_BUFFER_TIMEOUT
from src.logger import get_logger

logger = get_logger("buffer")

BufferedItem = Tuple[int, Dict[str, Any]]


class EventBuffer:
    """Collects numbered events and flushes them after a quiet period."""

    def __init__(self, flush_callback: Callable[[List[BufferedItem]], Awaitable[None]]):
        self.buffer: List[BufferedItem] = []
        self.flush_callback = flush_callback
        self._timer_task: Optional[asyncio.Task] = None

    def add_event(self, event: BufferedItem):
        """Append an event and restart the debounce timer."""
        self.buffer.append(event)
        self._restart_timer()

    def _restart_timer(self):
        if self._timer_task:
            self._timer_task.cancel()
        self._timer_task = asyncio.create_task(self._timer())

    async def _timer(self):
        try:
            await asyncio.sleep(EVENT_BUFFER_TIMEOUT)
            await self._flush()
        except asyncio.CancelledError:
            # This is expected when the timer is restarted
            pass
        except Exception as e:
            logger.error("Error in buffer timer: %s", e)

    async def _flush(self):
        if not self.buffer:
            return
        events_copy = self.buffer.copy()
        self.buffer.clear()
        self._timer_task = None
        try:
            await self.flush_callback(events_copy)
        except Exception as e:
            logger.error("Error during buffer flush callback: %s", e)
            self.buffer.extend(events_copy)

    async def force_flush(self):
        """Flush the buffer immediately, cancelling the pending timer."""
        if self._timer_task:
            self._timer_task.cancel()
            self._timer_task = None
        if self.buffer:
            await self._flush()
