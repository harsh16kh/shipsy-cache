"""Event emission utilities for cache lifecycle hooks."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections import defaultdict
from typing import Any, Callable, DefaultDict, Dict, List


LOGGER = logging.getLogger(__name__)


class CacheEventEmitter:
    """Emit structured cache lifecycle events to registered listeners."""

    def __init__(self) -> None:
        """Initialize an empty event listener registry."""

        self._listeners: DefaultDict[str, List[Callable[..., Any]]] = defaultdict(list)

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        """Register a listener for a named cache event.

        Args:
            event: The event name to subscribe to.
            callback: The listener callable. Sync callbacks are called directly;
                async callbacks are scheduled on the running event loop.
        """

        self._listeners[event].append(callback)

    def emit(self, event: str, payload: Dict[str, Any]) -> None:
        """Emit an event payload to all registered listeners.

        Listener failures are logged and never propagated into cache logic.

        Args:
            event: The event name to emit.
            payload: Structured event payload.
        """

        listeners = list(self._listeners.get(event, []))
        if not listeners:
            return

        for callback in listeners:
            try:
                result = callback(payload)
                if inspect.isawaitable(result):
                    self._schedule_async_listener(event, callback, result)
            except Exception:  # pragma: no cover - defensive logging path
                LOGGER.exception("Cache listener failed for event '%s'.", event)

    def _schedule_async_listener(
        self,
        event: str,
        callback: Callable[..., Any],
        awaitable: Any,
    ) -> None:
        """Schedule an async listener without blocking the caller."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            LOGGER.warning(
                "Dropping async cache listener for event '%s' because no running loop exists.",
                event,
            )
            return

        task = loop.create_task(awaitable)
        task.add_done_callback(
            lambda done: self._handle_async_listener_result(event, callback, done),
        )

    def _handle_async_listener_result(
        self,
        event: str,
        callback: Callable[..., Any],
        task: "asyncio.Task[Any]",
    ) -> None:
        """Log async listener failures after the scheduled task completes."""

        try:
            task.result()
        except Exception:  # pragma: no cover - defensive logging path
            LOGGER.exception(
                "Async cache listener failed for event '%s' via %r.",
                event,
                callback,
            )
