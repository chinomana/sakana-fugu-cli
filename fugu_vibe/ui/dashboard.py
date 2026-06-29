"""
Main orchestration dashboard using Rich for real-time visualization
of Fugu's internal multi-agent coordination.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

import structlog
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from fugu_vibe.core.event_bus import Event, EventBus, EventType
from fugu_vibe.core.orchestration import OrchestrationPhase, OrchestrationState
from fugu_vibe.ui.components import OrchestrationTimeline, TaskTree, TokenMeter

if TYPE_CHECKING:
    from fugu_vibe.config import Config

logger = structlog.get_logger()


class OrchestrationDashboard:
    """
    Real-time dashboard showing Fugu's internal orchestration.

    Layout:
    ┌──────────────────────────────────────────────┐
    │ 🐡 Fugu Ultra - Orchestration Dashboard      │
    ├──────────────────┬───────────────────────────┤
    │ Orchestration    │ Streaming Content         │
    │ Timeline         │                           │
    │ (routing,        │ [live output from Fugu]   │
    │  workers,        │                           │
    │  verification)   │                           │
    ├──────────────────┼───────────────────────────┤
    │ Token Meter      │ Task Tree                 │
    │ (3 categories)   │ (active tasks)            │
    ├──────────────────┴───────────────────────────┤
    │ Status Bar                                     │
    └────────────────────────────────────────────────┘
    """

    def __init__(self, config: Config, event_bus: EventBus):
        self.config = config
        self.event_bus = event_bus
        self.console = Console()

        # Components
        self.timeline = OrchestrationTimeline()
        self.token_meter = TokenMeter()
        self.task_tree = TaskTree()

        # State
        self._orch_state = OrchestrationState()
        self._stream_content: list[str] = []
        self._max_content_lines = 50
        self._running = False
        self._live: Live | None = None
        self._update_task: asyncio.Task | None = None

        # Layout configuration
        self.layout = self._create_layout()

    def _create_layout(self) -> Layout:
        """Create the dashboard layout."""
        layout = Layout(name="root")

        # Header
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=1),
        )

        # Main area: left (orchestration) + right (content)
        layout["main"].split_row(
            Layout(name="left", ratio=1),
            Layout(name="right", ratio=2),
        )

        # Left: timeline + tokens
        layout["left"].split_column(
            Layout(name="timeline", ratio=2),
            Layout(name="tokens", ratio=1),
        )

        # Right: content + tasks
        layout["right"].split_column(
            Layout(name="content", ratio=3),
            Layout(name="tasks", ratio=1),
        )

        return layout

    async def start(self) -> None:
        """Start the dashboard display."""
        self._running = True

        # Subscribe to events
        self.event_bus.on(EventType.ORCH_ROUTING, self._on_routing)
        self.event_bus.on(EventType.ORCH_WORKER, self._on_worker)
        self.event_bus.on(EventType.ORCH_VERIFY, self._on_verify)
        self.event_bus.on(EventType.ORCH_DONE, self._on_done)
        self.event_bus.on(EventType.STREAM_CONTENT, self._on_content)
        self.event_bus.on(EventType.STREAM_REASONING, self._on_reasoning)
        self.event_bus.on(EventType.STREAM_TOOL_CALL, self._on_tool_call)
        self.event_bus.on(EventType.STREAM_TOOL_RESULT, self._on_tool_result)
        self.event_bus.on(EventType.STREAM_TOKEN_USAGE, self._on_stream_token_usage)
        self.event_bus.on(EventType.TOKEN_UPDATE, self._on_token_update)
        self.event_bus.on(EventType.TASK_CREATED, self._on_task_update)
        self.event_bus.on(EventType.TASK_STARTED, self._on_task_update)
        self.event_bus.on(EventType.TASK_COMPLETED, self._on_task_update)

        self._render_layout()

        # Start live display
        self._live = Live(
            self.layout,
            console=self.console,
            refresh_per_second=4,
            screen=False,
        )
        self._live.start()

        # Start update loop
        self._update_task = asyncio.create_task(self._update_loop())

        logger.info("dashboard_started")

    async def stop(self) -> None:
        """Stop the dashboard display."""
        self._running = False

        if self._update_task:
            self._update_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._update_task

        if self._live:
            self._live.stop()

        logger.info("dashboard_stopped")

    async def _update_loop(self) -> None:
        """Periodically update the dashboard display."""
        while self._running:
            try:
                self._render_layout()
                await asyncio.sleep(0.25)  # 4 FPS
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("dashboard_update_error")

    def _render_layout(self) -> None:
        """Render all dashboard panels."""
        # Header
        self.layout["header"].update(self._render_header())

        # Timeline
        self.layout["timeline"].update(
            Panel(self.timeline.render(), title="📊 Orchestration Timeline", border_style="cyan")
        )

        # Token meter
        self.layout["tokens"].update(
            Panel(self.token_meter.render(), title="💰 Token Usage", border_style="green")
        )

        # Content
        self.layout["content"].update(
            Panel(self._render_content(), title="📝 Output", border_style="blue")
        )

        # Tasks
        self.layout["tasks"].update(
            Panel(self.task_tree.render(), title="📋 Tasks", border_style="yellow")
        )

        # Footer
        self.layout["footer"].update(self._render_footer())

    def _render_header(self) -> Panel:
        """Render dashboard header."""
        phase_icon = {
            OrchestrationPhase.IDLE: "⏳",
            OrchestrationPhase.ROUTING: "🧭",
            OrchestrationPhase.WORKER_ACTIVE: "⚡",
            OrchestrationPhase.VERIFYING: "🔍",
            OrchestrationPhase.SYNTHESIZING: "🔄",
            OrchestrationPhase.DONE: "✅",
            OrchestrationPhase.ERROR: "❌",
        }.get(self._orch_state.phase, "❓")

        header_text = Text()
        header_text.append("🐡 ", style="bold cyan")
        header_text.append("Fugu Vibe CLI", style="bold white")
        header_text.append("  |  ", style="dim")
        header_text.append(f"{phase_icon} {self._orch_state.phase.value.upper()}", style="bold yellow")
        header_text.append("  |  ", style="dim")
        header_text.append(f"Workers: {self._orch_state.active_workers}", style="cyan")
        header_text.append("  |  ", style="dim")
        header_text.append(f"Elapsed: {self._orch_state.elapsed:.1f}s", style="green")

        return Panel(header_text, style="on_dark_blue")

    def _render_content(self) -> Text:
        """Render streaming content panel."""
        content = Text()
        lines = self._stream_content[-self._max_content_lines:]
        if not lines:
            content.append("Waiting for workspace events...", style="dim")
            return content
        for i, line in enumerate(lines):
            content.append(line)
            if i < len(lines) - 1:
                content.append("\n")
        return content

    def _render_footer(self) -> Text:
        """Render status footer."""
        footer = Text()
        footer.append(" Press ", style="dim")
        footer.append("Ctrl+C", style="bold white")
        footer.append(" to cancel  |  ", style="dim")
        footer.append("Space", style="bold white")
        footer.append(" for voice  |  ", style="dim")
        footer.append("?", style="bold white")
        footer.append(" for help", style="dim")
        return footer

    # Event handlers
    def _on_routing(self, event: Event) -> None:
        self._orch_state.phase = OrchestrationPhase.ROUTING
        self._orch_state.routing_model = event.data.get("model")
        self._orch_state.routing_confidence = event.data.get("confidence")
        self.timeline.add_event("🧭", f"Routing: {event.data.get('model', 'unknown')}", "cyan")

    def _on_worker(self, event: Event) -> None:
        self._orch_state.phase = OrchestrationPhase.WORKER_ACTIVE
        worker_id = event.data.get("worker_id", "W?")
        self.timeline.add_event("⚡", f"Worker {worker_id} active", "yellow")

    def _on_verify(self, event: Event) -> None:
        self._orch_state.phase = OrchestrationPhase.VERIFYING
        self.timeline.add_event("🔍", "Self-verification", "magenta")

    def _on_done(self, event: Event) -> None:
        self._orch_state.phase = OrchestrationPhase.DONE
        self.timeline.add_event("✅", "Orchestration complete", "green")

    def _on_content(self, event: Event) -> None:
        content = event.data.get("content", "")
        if content:
            prefix = "[stream] " if event.data.get("provisional") else ""
            lines = content.split("\n")
            if lines:
                lines[0] = prefix + lines[0]
            self._stream_content.extend(lines)

    def _on_reasoning(self, event: Event) -> None:
        content = event.data.get("content", "")
        if content:
            self._stream_content.append(f"[thinking] {content}")

    def _on_tool_call(self, event: Event) -> None:
        tool_call = event.data.get("tool_call", {})
        name = tool_call.get("name", "unknown") if isinstance(tool_call, dict) else "unknown"
        self._stream_content.append(f"[tool] {name}")

    def _on_tool_result(self, event: Event) -> None:
        tool_call = event.data.get("tool_call", {})
        name = tool_call.get("name", "unknown") if isinstance(tool_call, dict) else "unknown"
        status = "ok" if event.data.get("ok") else "error"
        summary = event.data.get("summary", "")
        self._stream_content.append(f"[tool:{status}] {name} {summary}".rstrip())

    def _on_stream_token_usage(self, event: Event) -> None:
        self.token_meter.update(
            input_tokens=event.data.get("input_tokens", 0),
            output_tokens=event.data.get("output_tokens", 0),
            orchestration_tokens=event.data.get("orchestration_tokens", 0),
        )

    def _on_token_update(self, event: Event) -> None:
        self.token_meter.update(
            input_tokens=event.data.get("input_tokens", 0),
            output_tokens=event.data.get("output_tokens", 0),
            orchestration_tokens=event.data.get("orchestration_tokens", 0),
        )

    def _on_task_update(self, event: Event) -> None:
        self.task_tree.update_task(event.data)
