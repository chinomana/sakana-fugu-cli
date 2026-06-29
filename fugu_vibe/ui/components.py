"""
Reusable TUI components for the orchestration dashboard.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table
from rich.text import Text
from rich.tree import Tree


@dataclass
class TimelineEvent:
    """Single event on the orchestration timeline."""

    icon: str
    message: str
    color: str
    timestamp: float = 0.0


class OrchestrationTimeline:
    """
    Visual timeline showing orchestration phase transitions.
    """

    def __init__(self, max_events: int = 20):
        self.events: deque[TimelineEvent] = deque(maxlen=max_events)
        self._progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{Task.description}"),
            transient=True,
        )

    def add_event(self, icon: str, message: str, color: str = "white") -> None:
        """Add an event to the timeline."""
        import time
        self.events.append(TimelineEvent(
            icon=icon,
            message=message,
            color=color,
            timestamp=time.monotonic(),
        ))

    def render(self) -> Text:
        """Render the timeline as Rich Text."""
        result = Text()

        for i, event in enumerate(self.events):
            # Icon
            result.append(f"{event.icon} ", style=event.color)
            # Message
            result.append(event.message, style=event.color)

            if i < len(self.events) - 1:
                result.append("\n")

        if not self.events:
            result.append("Waiting for orchestration to start...", style="dim")

        return result


class TokenMeter:
    """
    Three-category token usage meter:
    - Input tokens (user content)
    - Output tokens (model response)
    - Orchestration tokens (Fugu coordination overhead)
    """

    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.orchestration_tokens = 0

    def update(self, input_tokens: int = 0, output_tokens: int = 0, orchestration_tokens: int = 0) -> None:
        """Update token counts."""
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.orchestration_tokens = orchestration_tokens

    def render(self) -> Table:
        """Render token meter as Rich Table."""
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column("Category", style="bold")
        table.add_column("Count", justify="right")
        table.add_column("Bar", width=20)

        total = max(self.input_tokens + self.output_tokens + self.orchestration_tokens, 1)

        # Input tokens
        input_bar = "█" * int(20 * self.input_tokens / total)
        table.add_row(
            "📥 Input",
            f"{self.input_tokens:,}",
            Text(input_bar, style="blue"),
        )

        # Output tokens
        output_bar = "█" * int(20 * self.output_tokens / total)
        table.add_row(
            "📤 Output",
            f"{self.output_tokens:,}",
            Text(output_bar, style="green"),
        )

        # Orchestration tokens (the unique Fugu metric)
        orch_bar = "█" * int(20 * self.orchestration_tokens / total)
        table.add_row(
            "⚙️  Orchestration",
            f"{self.orchestration_tokens:,}",
            Text(orch_bar, style="yellow"),
        )

        # Total
        table.add_row(
            "📊 Total",
            f"{self.input_tokens + self.output_tokens + self.orchestration_tokens:,}",
            Text("─" * 20, style="dim"),
            style="bold",
        )

        # Orchestration ratio
        if total > 0:
            ratio = self.orchestration_tokens / total * 100
            table.add_row(
                "⚡ Orch Ratio",
                f"{ratio:.1f}%",
                "",
                style="dim" if ratio < 20 else "yellow" if ratio < 50 else "red",
            )

        return table


class TaskTree:
    """
    Hierarchical tree view of active tasks with their dependencies.
    """

    def __init__(self):
        self.tasks: dict[str, dict] = {}

    def update_task(self, data: dict) -> None:
        """Update or add a task."""
        task_id = data.get("task_id", "")
        self.tasks[task_id] = data

    def render(self) -> Tree:
        """Render task tree."""
        root = Tree("📋 Active Tasks")

        status_icons = {
            "pending": "⏳",
            "queued": "📥",
            "running": "🔄",
            "completed": "✅",
            "failed": "❌",
            "cancelled": "🚫",
            "merged": "🔀",
        }

        for task_id, task in self.tasks.items():
            status = task.get("status", "unknown")
            icon = status_icons.get(status, "❓")
            name = task.get("name", task_id)
            model = task.get("model", "")

            node = root.add(f"{icon} {name} [{model}]")

            # Add details
            if task.get("duration"):
                node.add(f"⏱️  {task['duration']:.1f}s")

            deps = task.get("depends_on", [])
            if deps:
                deps_str = ", ".join(deps)
                node.add(f"🔗 {deps_str}")

        if not self.tasks:
            root.add("No active tasks")

        return root


class VoiceIndicator:
    """
    Visual indicator for voice input status.
    """

    def __init__(self):
        self.is_recording = False
        self.audio_level = 0.0
        self.transcribed_text = ""

    def set_recording(self, recording: bool) -> None:
        self.is_recording = recording

    def set_level(self, level: float) -> None:
        self.audio_level = level

    def set_text(self, text: str) -> None:
        self.transcribed_text = text

    def render(self) -> Text:
        """Render voice status indicator."""
        result = Text()

        if self.is_recording:
            # Animated recording indicator
            bars = int(self.audio_level * 10)
            meter = "█" * bars + "░" * (10 - bars)
            result.append("🎤 ", style="red")
            result.append("RECORDING ", style="bold red")
            result.append(f"[{meter}]", style="red")
        else:
            result.append("🎤 ", style="dim")
            result.append("Standby ", style="dim")
            result.append("[░░░░░░░░░░]", style="dim")

        if self.transcribed_text:
            result.append(f"  \"{self.transcribed_text[:50]}\"", style="italic cyan")

        return result
