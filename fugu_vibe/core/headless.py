"""Headless and SDK entry points for non-interactive Fugu runs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fugu_vibe.agent.loop import AgentLoop
from fugu_vibe.agent.registry import ToolRegistry
from fugu_vibe.api.client import FuguClient
from fugu_vibe.config import Config
from fugu_vibe.core.effort import select_effort
from fugu_vibe.core.event_bus import EventBus
from fugu_vibe.core.event_log import EventLogWriter
from fugu_vibe.core.instructions import build_instructions
from fugu_vibe.core.orchestration import OrchestrationAnalyzer
from fugu_vibe.mcp import MCPConfigStore, MCPToolManager
from fugu_vibe.tools import FileTools, GitTools, TerminalTool

DEFAULT_HEADLESS_INSTRUCTIONS = """You are running in fugu-vibe headless mode.
Use structured workspace tools when needed, verify changes when practical, and finish with a concise result summary.
If changes are needed, call file_edit or file_write instead of printing patches. After edits, use compile/test/lint results to repair failures before finalizing. Only output a diff when tool calls are unavailable or writes fail.
"""


@dataclass
class HeadlessResult:
    """Structured result from a non-interactive run."""

    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    effort: str = "xhigh"
    automatic_verification: dict[str, int] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return bool(self.content or self.tool_calls)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "content": self.content,
            "tool_calls": self.tool_calls,
            "rounds": self.rounds,
            "effort": self.effort,
            "automatic_verification": self.automatic_verification,
        }


async def run_headless(
    prompt: str,
    config: Config | None = None,
    *,
    workspace: Path | str | None = None,
    client: Any | None = None,
    event_bus: EventBus | None = None,
    instructions: str | None = None,
    log_events: bool = True,
) -> HeadlessResult:
    """Run one Fugu task without an interactive prompt."""
    config = config or Config()
    workspace_path = await asyncio.to_thread(
        lambda: Path(workspace or Path.cwd()).expanduser().resolve()
    )
    own_client = client is None
    own_bus = event_bus is None
    event_bus = event_bus or EventBus()
    await event_bus.start()
    if log_events:
        EventLogWriter(event_bus, workspace_path / ".fugu-vibe" / "events.jsonl").start()

    fugu_client = client or FuguClient(config)
    try:
        registry = build_headless_registry(config, workspace_path)
        effort_decision = select_effort(
            prompt,
            config.model.reasoning_effort,  # type: ignore[arg-type]
            adaptive=config.model.adaptive_effort,
        )
        final_instructions = instructions or build_instructions(
            DEFAULT_HEADLESS_INSTRUCTIONS,
            workspace_path,
        )
        response_parts: list[str] = []
        analyzer = OrchestrationAnalyzer(config, event_bus)
        loop = AgentLoop(
            fugu_client,
            registry,
            event_bus,
            max_tool_rounds=config.tools.max_tool_rounds,
            auto_test_after_edit=config.tools.auto_test_after_edit,
            auto_test_command=config.tools.auto_test_command,
            auto_compile_after_edit=config.tools.auto_compile_after_edit,
            auto_lint_after_edit=config.tools.auto_lint_after_edit,
            auto_lint_command=config.tools.auto_lint_command,
        )
        result = await loop.run(
            messages=[{"role": "user", "content": prompt}],
            model=config.model.default,
            effort=effort_decision.effort,
            web_search=False,
            instructions=final_instructions,
            max_output_tokens=min(config.model.max_output_tokens, 4096),
            on_content=response_parts.append,
            on_chunk=analyzer.analyze_chunk,
        )
        await analyzer.finalize()
        content = "".join(response_parts) or result.content
        return HeadlessResult(
            content=content,
            tool_calls=result.tool_calls,
            rounds=result.rounds,
            effort=effort_decision.effort,
            automatic_verification=result.automatic_verification,
        )
    finally:
        if own_client:
            await fugu_client.close()
        if own_bus:
            await event_bus.close()


def build_headless_registry(config: Config, workspace: Path) -> ToolRegistry:
    """Build the default non-interactive tool registry."""
    mcp_tools = None
    if config.mcp.enabled:
        mcp_tools = MCPToolManager(
            MCPConfigStore(workspace),
            timeout_seconds=config.mcp.timeout_seconds,
        )
    return ToolRegistry(
        FileTools(workspace, safety_mode=config.safety.mode),
        terminal_tool=TerminalTool(
            workspace,
            enabled=config.tools.terminal_enabled,
            approval=config.tools.terminal_approval,
            safety_mode=config.safety.mode,
            timeout_seconds=config.tools.terminal_timeout_seconds,
            max_output_chars=config.tools.max_output_chars,
        ),
        git_tools=GitTools(workspace, max_output_chars=config.tools.max_output_chars),
        mcp_tools=mcp_tools,
    )
