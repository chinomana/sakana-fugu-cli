"""
Main orchestration dashboard using Rich for real-time visualization
of Fugu's internal multi-agent coordination.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import TYPE_CHECKING

import structlog
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
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
        self._routing_confidence: float | None = None
        self._last_budget_alert: dict | None = None
        self._agent_status = "idle"
        self._agent_round = 0
        self._agent_max_rounds = 0
        self._tools_enabled = False
        self._tool_count = 0
        self._current_tool = ""
        self._current_action = "Waiting for instructions"
        self._last_tool_status = ""
        self._last_tool_summary = ""
        self._last_result_text = ""
        self._last_mutated_paths: list[str] = []
        self._automatic_verification: dict[str, object] = {}
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

        # Right: agent state + content + tasks
        layout["right"].split_column(
            Layout(name="agent", size=9),
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
        self.event_bus.on(EventType.AGENT_ROUND_START, self._on_agent_round_start)
        self.event_bus.on(EventType.AGENT_ROUND_END, self._on_agent_round_end)
        self.event_bus.on(EventType.AGENT_DONE, self._on_agent_done)
        self.event_bus.on(EventType.AGENT_STOPPED, self._on_agent_stopped)
        self.event_bus.on(EventType.STREAM_CONTENT, self._on_content)
        self.event_bus.on(EventType.STREAM_REASONING, self._on_reasoning)
        self.event_bus.on(EventType.STREAM_TOOL_CALL, self._on_tool_call)
        self.event_bus.on(EventType.STREAM_TOOL_RESULT, self._on_tool_result)
        self.event_bus.on(EventType.STREAM_TOKEN_USAGE, self._on_stream_token_usage)
        self.event_bus.on(EventType.TOKEN_UPDATE, self._on_token_update)
        self.event_bus.on(EventType.TASK_CREATED, self._on_task_update)
        self.event_bus.on(EventType.TASK_STARTED, self._on_task_update)
        self.event_bus.on(EventType.TASK_COMPLETED, self._on_task_update)
        self.event_bus.on(EventType.TASK_PROGRESS, self._on_task_update)
        self.event_bus.on(EventType.TASK_FAILED, self._on_task_update)
        self.event_bus.on(EventType.TASK_CANCELLED, self._on_task_update)

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

        # Agent state
        self.layout["agent"].update(
            Panel(self._render_agent_status(), title="🤖 Agent State", border_style="magenta")
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
        if self._routing_confidence is not None:
            header_text.append("  |  ", style="dim")
            header_text.append(f"Routing: {self._routing_confidence:.0%}", style="magenta")
        if self._last_budget_alert:
            header_text.append("  |  ", style="dim")
            level = str(self._last_budget_alert.get("level", "warning")).upper()
            header_text.append(f"Budget: {level}", style="red" if level == "CRITICAL" else "yellow")

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

    def _render_agent_status(self) -> Table:
        """Render current local agent/tool execution status."""
        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Field", style="bold")
        table.add_column("Value")
        status_label = self._display_status_label(self._agent_status)
        status_style = self._display_status_style(self._agent_status)
        table.add_row("State", Text(status_label, style=status_style))
        table.add_row("Now", self._current_action or "-")
        round_value = f"{self._agent_round}/{self._agent_max_rounds}" if self._agent_max_rounds else "-"
        table.add_row("Round", round_value)
        table.add_row("Tools", f"{self._tool_count} {'available' if self._tools_enabled else 'disabled'}")
        table.add_row("Tool", self._current_tool or "-")
        table.add_row("Last result", self._last_result_text or "-")
        table.add_row("Auto checks", self._verification_text())
        table.add_row("Changed", ", ".join(self._last_mutated_paths[-3:]) or "-")
        return table

    def _verification_text(self) -> str:
        if not self._automatic_verification:
            return "-"
        total = int(self._automatic_verification.get("total", 0) or 0)
        failed = int(self._automatic_verification.get("failed", 0) or 0)
        status = str(self._automatic_verification.get("status", "not_run"))
        if failed and status != "failed":
            outcome = f"{status}, {failed} failed"
        elif failed:
            outcome = f"{failed} failed"
        else:
            outcome = status
        parts = [
            f"{total} total",
            f"compile {self._automatic_verification.get('compile', 0)}",
            f"lint {self._automatic_verification.get('lint', 0)}",
            f"test {self._automatic_verification.get('test', 0)}",
            outcome,
        ]
        return " · ".join(parts)

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
        self._routing_confidence = event.data.get("confidence")
        model = event.data.get("model", "unknown")
        message = event.data.get("message") or f"Routing: {model}"
        self.timeline.add_event("🧭", message, "cyan")

    def _on_agent_round_start(self, event: Event) -> None:
        self._agent_status = "thinking"
        self._agent_round = int(event.data.get("round", self._agent_round) or 0)
        self._agent_max_rounds = int(event.data.get("max_rounds", self._agent_max_rounds) or 0)
        self._tools_enabled = bool(event.data.get("tools_enabled"))
        self._tool_count = int(event.data.get("tool_count", self._tool_count) or 0)
        self._current_tool = ""
        self._current_action = "Understanding the request and choosing the next step"
        self.timeline.add_event("🤖", f"Round {self._agent_round}: planning next step", "cyan")

    def _on_agent_round_end(self, event: Event) -> None:
        self._agent_status = "thinking"
        self._update_verification(event.data.get("automatic_verification"))
        paths = event.data.get("mutated_paths")
        if isinstance(paths, list):
            self._last_mutated_paths = [str(path) for path in paths]
            if self._last_mutated_paths:
                self._current_action = "Reviewing tool results before continuing"
        self.timeline.add_event("↩", f"Round {event.data.get('round', '?')} complete", "cyan")

    def _on_agent_done(self, event: Event) -> None:
        self._agent_status = "done"
        self._current_tool = ""
        self._update_verification(event.data.get("automatic_verification"))
        self._current_action = "Finished and ready to summarize"
        self.timeline.add_event("✅", "Agent completed", "green")

    def _on_agent_stopped(self, event: Event) -> None:
        self._agent_status = "stopped"
        self._current_tool = ""
        self._update_verification(event.data.get("automatic_verification"))
        reason = event.data.get("reason", "stopped")
        self._current_action = f"Stopped: {reason}"
        self.timeline.add_event("🛑", f"Agent stopped: {reason}", "red")

    def _update_verification(self, verification: object) -> None:
        if isinstance(verification, dict):
            self._automatic_verification = verification

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
        arguments = self._tool_arguments(tool_call)
        automatic = bool(event.data.get("automatic"))
        self._current_tool = str(name)
        self._agent_status = self._status_for_tool(str(name), arguments)
        self._current_action = self._action_for_tool(str(name), arguments, automatic=automatic)
        marker = "auto-check" if automatic else "tool"
        self._stream_content.append(f"[{marker}] {self._current_action}")

    def _on_tool_result(self, event: Event) -> None:
        tool_call = event.data.get("tool_call", {})
        name = tool_call.get("name", "unknown") if isinstance(tool_call, dict) else "unknown"
        arguments = self._tool_arguments(tool_call)
        ok = bool(event.data.get("ok"))
        status = "ok" if ok else "error"
        summary = event.data.get("summary", "")
        self._last_tool_status = status
        self._last_tool_summary = str(summary)
        self._last_result_text = self._result_text(str(name), ok, str(summary), arguments)
        self._current_tool = ""
        self._agent_status = "thinking" if ok else "repairing"
        self._current_action = (
            "Using the result to decide the next step"
            if ok
            else "Validation failed; feeding the error back so the agent can fix it"
        )
        self._stream_content.append(f"[{status}] {self._last_result_text}")

    def _tool_arguments(self, tool_call: object) -> dict[str, object]:
        if not isinstance(tool_call, dict):
            return {}
        raw_arguments = tool_call.get("arguments", {})
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if isinstance(raw_arguments, str) and raw_arguments.strip():
            try:
                parsed = json.loads(raw_arguments)
            except json.JSONDecodeError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _status_for_tool(self, name: str, arguments: dict[str, object] | None = None) -> str:
        arguments = arguments or {}
        command = str(arguments.get("command", ""))
        if name in {"file_list", "file_glob", "file_read", "file_search", "file_grep"}:
            return "inspecting"
        if name in {"file_write", "file_edit", "file_delete", "file_mkdir"}:
            return "editing"
        if name == "run_test" or "pytest" in command:
            return "testing"
        if name == "run_lint" or "ruff" in command:
            return "linting"
        if name == "bash" and "py_compile" in command:
            return "compiling"
        if name == "bash":
            return "running"
        if name.startswith("git_"):
            return "reviewing"
        return "using_tool"

    def _action_for_tool(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        automatic: bool = False,
    ) -> str:
        prefix = "Auto-check: " if automatic else ""
        path = self._argument_text(arguments, "path")
        command = self._argument_text(arguments, "command")
        pattern = self._argument_text(arguments, "pattern")
        query = self._argument_text(arguments, "query")
        if name == "file_list":
            return f"{prefix}Listing workspace files"
        if name == "file_glob":
            return f"{prefix}Finding files matching {pattern or '**/*'}"
        if name == "file_read":
            return f"{prefix}Reading {path or 'a file'}"
        if name in {"file_search", "file_grep"}:
            target = query or self._argument_text(arguments, "pattern_regex") or "text"
            return f"{prefix}Searching for {target}"
        if name == "file_write":
            return f"{prefix}Writing {path or 'a file'}"
        if name == "file_edit":
            return f"{prefix}Editing {path or 'a file'}"
        if name == "file_delete":
            return f"{prefix}Deleting {path or 'a file'}"
        if name == "file_mkdir":
            return f"{prefix}Creating directory {path or ''}".strip()
        if name == "run_test" or "pytest" in command:
            return f"{prefix}Running tests: {command or 'pytest'}"
        if name == "run_lint" or "ruff" in command:
            return f"{prefix}Running lint: {command or 'python -m ruff check .'}"
        if name == "bash" and "py_compile" in command:
            return f"{prefix}Checking Python syntax: {command}"
        if name == "bash":
            return f"{prefix}Running command: {command or 'shell command'}"
        if name == "git_status":
            return f"{prefix}Checking git status"
        if name == "git_diff":
            return f"{prefix}Reviewing git diff"
        return f"{prefix}Using {name}"

    def _result_text(
        self,
        name: str,
        ok: bool,
        summary: str,
        arguments: dict[str, object],
    ) -> str:
        label = self._result_label(name, arguments)
        if ok:
            return f"{label} passed" + (f": {summary}" if summary else "")
        return f"{label} failed" + (f": {summary}" if summary else "")

    def _result_label(self, name: str, arguments: dict[str, object]) -> str:
        path = self._argument_text(arguments, "path")
        command = self._argument_text(arguments, "command")
        if name in {"file_read", "file_write", "file_edit", "file_delete"}:
            return path or name
        if name == "file_mkdir":
            return f"directory {path}" if path else "directory operation"
        if name == "run_test" or "pytest" in command:
            return "Tests"
        if name == "run_lint" or "ruff" in command:
            return "Lint"
        if name == "bash" and "py_compile" in command:
            return "Python syntax check"
        if name == "bash":
            return "Command"
        if name.startswith("git_"):
            return "Git check"
        return name

    def _argument_text(self, arguments: dict[str, object], key: str) -> str:
        value = arguments.get(key)
        return str(value) if value is not None else ""

    def _display_status_label(self, status: str) -> str:
        labels = {
            "idle": "Waiting",
            "thinking": "Planning next step",
            "inspecting": "Inspecting files",
            "editing": "Editing workspace",
            "compiling": "Checking syntax",
            "testing": "Running tests",
            "linting": "Running lint",
            "running": "Running command",
            "reviewing": "Reviewing changes",
            "using_tool": "Using tool",
            "repairing": "Fixing a failed check",
            "done": "Done",
            "stopped": "Stopped",
        }
        return labels.get(status, status)

    def _display_status_style(self, status: str) -> str:
        if status in {"done"}:
            return "green"
        if status in {"repairing", "stopped"}:
            return "red"
        if status in {"compiling", "testing", "linting"}:
            return "magenta"
        if status in {"inspecting", "editing", "reviewing", "using_tool", "running"}:
            return "cyan"
        if status == "thinking":
            return "yellow"
        return "dim"

    def _on_stream_token_usage(self, event: Event) -> None:
        self._update_token_meter(event.data)

    def _on_token_update(self, event: Event) -> None:
        self._update_token_meter(event.data)

    def _update_token_meter(self, data: dict) -> None:
        budget_alert = data.get("budget_alert") if isinstance(data.get("budget_alert"), dict) else None
        if budget_alert:
            self._last_budget_alert = budget_alert
            self._stream_content.append(f"[budget:{budget_alert.get('level')}] {budget_alert.get('message')}")
        self.token_meter.update(
            input_tokens=data.get("input_tokens", self.token_meter.input_tokens),
            output_tokens=data.get("output_tokens", self.token_meter.output_tokens),
            orchestration_tokens=data.get("orchestration_tokens", self.token_meter.orchestration_tokens),
            estimated_cost_usd=data.get("estimated_cost_usd") or (budget_alert or {}).get("estimated_cost_usd"),
            budget_alert=budget_alert,
        )

    def _on_task_update(self, event: Event) -> None:
        self.task_tree.update_task(event.data)
