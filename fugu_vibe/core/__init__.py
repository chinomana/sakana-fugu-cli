"""Core engine: task management, orchestration analysis, and event system."""

from typing import Any

from fugu_vibe.core.event_bus import EventBus, EventType
from fugu_vibe.core.orchestration import OrchestrationAnalyzer, OrchestrationEvent
from fugu_vibe.core.task_manager import Task, TaskManager, TaskStatus


def __getattr__(name: str) -> Any:
    if name in {"HeadlessResult", "build_headless_registry", "run_headless"}:
        from fugu_vibe.core import headless

        return getattr(headless, name)
    raise AttributeError(name)


__all__ = [
    "EventBus",
    "EventType",
    "HeadlessResult",
    "OrchestrationAnalyzer",
    "OrchestrationEvent",
    "Task",
    "TaskManager",
    "TaskStatus",
    "build_headless_registry",
    "run_headless",
]
