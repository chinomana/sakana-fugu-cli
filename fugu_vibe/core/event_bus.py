"""Async event bus for decoupled component communication."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

logger = structlog.get_logger()


class EventType(Enum):
    """Core event types for the Fugu Vibe CLI."""

    # Orchestration events
    ORCH_START = "orchestration:start"
    ORCH_ROUTING = "orchestration:routing"
    ORCH_WORKER = "orchestration:worker"
    ORCH_VERIFY = "orchestration:verify"
    ORCH_DONE = "orchestration:done"
    ORCH_ERROR = "orchestration:error"

    # Stream events
    STREAM_CONTENT = "stream:content"
    STREAM_REASONING = "stream:reasoning"
    STREAM_TOOL_CALL = "stream:tool_call"
    STREAM_TOOL_RESULT = "stream:tool_result"
    STREAM_TOKEN_USAGE = "stream:token_usage"
    STREAM_DONE = "stream:done"
    STREAM_ERROR = "stream:error"

    # Task events
    TASK_CREATED = "task:created"
    TASK_STARTED = "task:started"
    TASK_PROGRESS = "task:progress"
    TASK_COMPLETED = "task:completed"
    TASK_FAILED = "task:failed"
    TASK_CANCELLED = "task:cancelled"

    # Voice events
    VOICE_RECORDING = "voice:recording"
    VOICE_TRANSCRIBED = "voice:transcribed"
    VOICE_COMMAND = "voice:command"
    VOICE_ERROR = "voice:error"

    # Token events
    TOKEN_UPDATE = "token:update"

    # System events
    HEARTBEAT = "system:heartbeat"
    SHUTDOWN = "system:shutdown"


@dataclass
class Event:
    """Event payload with type and data."""

    type: EventType
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=asyncio.get_event_loop().time)
    source: str = ""


class EventBus:
    """
    Async event bus for decoupled communication between CLI components.

    Usage:
        bus = EventBus()

        # Subscribe
        bus.on(EventType.ORCH_ROUTING, handler_func)

        # Emit
        await bus.emit(EventType.ORCH_ROUTING, {"model": "gpt-5.5", "confidence": 0.87})

        # Shutdown
        await bus.close()
    """

    def __init__(self):
        self._subscribers: dict[EventType, list[Callable[[Event], Any]]] = {
            et: [] for et in EventType
        }
        self._queue: asyncio.Queue[Event] = asyncio.Queue()
        self._dispatcher_task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the event dispatcher."""
        if not self._running:
            self._running = True
            self._dispatcher_task = asyncio.create_task(self._dispatch_loop())
            logger.info("event_bus_started")

    async def close(self) -> None:
        """Stop the event dispatcher."""
        self._running = False
        if self._dispatcher_task:
            self._dispatcher_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._dispatcher_task
        logger.info("event_bus_stopped")

    def on(self, event_type: EventType, handler: Callable[[Event], Any]) -> None:
        """Subscribe to an event type."""
        self._subscribers[event_type].append(handler)
        logger.debug("event_subscribed", event_type=event_type.value, handler=handler.__name__)

    def off(self, event_type: EventType, handler: Callable[[Event], Any]) -> None:
        """Unsubscribe from an event type."""
        if handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)

    async def emit(self, event_type: EventType, data: dict[str, Any] | None = None, source: str = "") -> None:
        """Emit an event to the bus."""
        event = Event(type=event_type, data=data or {}, source=source)
        await self._queue.put(event)

    async def _dispatch_loop(self) -> None:
        """Main dispatch loop processing events sequentially."""
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
                await self._handle_event(event)
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("event_dispatch_error")

    async def _handle_event(self, event: Event) -> None:
        """Dispatch event to all subscribers."""
        handlers = self._subscribers.get(event.type, [])
        if not handlers:
            return

        # Run handlers concurrently
        tasks = []
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    tasks.append(asyncio.create_task(result))
                elif asyncio.isfuture(result):
                    tasks.append(asyncio.ensure_future(result))
            except Exception:
                logger.exception("event_handler_error", handler=handler.__name__)

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
