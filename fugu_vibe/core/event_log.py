"""File-backed event log for cross-process dashboard viewing."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fugu_vibe.core.event_bus import Event, EventBus, EventType

DEFAULT_EVENT_LOG = Path(".fugu-vibe") / "events.jsonl"


def event_log_path(path: str | Path | None = None) -> Path:
    """Return the event log path for the current workspace."""
    return Path(path) if path else Path.cwd() / DEFAULT_EVENT_LOG


class EventLogWriter:
    """Subscribe to an EventBus and append events as JSON lines."""

    def __init__(self, event_bus: EventBus, path: str | Path | None = None):
        self.event_bus = event_bus
        self.path = event_log_path(path)

    def start(self, truncate: bool = True) -> None:
        """Create the log file and subscribe to all event types."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if truncate:
            self.path.write_text("")

        for event_type in EventType:
            self.event_bus.on(event_type, self.write)

    def write(self, event: Event) -> None:
        """Write a single event to disk."""
        payload = {
            "type": event.type.value,
            "data": event.data,
            "timestamp": event.timestamp,
            "source": event.source,
        }
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def parse_event_line(line: str) -> tuple[EventType, dict[str, Any], str] | None:
    """Parse one JSONL event record."""
    try:
        payload = json.loads(line)
        event_type = EventType(payload["type"])
    except (json.JSONDecodeError, KeyError, ValueError):
        return None

    data = payload.get("data")
    if not isinstance(data, dict):
        data = {}
    source = str(payload.get("source", "event_log"))
    return event_type, data, source
