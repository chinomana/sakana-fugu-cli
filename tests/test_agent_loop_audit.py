"""Tests for AgentLoop audit hardening."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fugu_vibe.agent.loop import DEFAULT_MAX_TOOL_ROUNDS, AgentLoop
from fugu_vibe.agent.registry import ToolRegistry
from fugu_vibe.api.stream_parser import StreamChunk
from fugu_vibe.core.event_bus import EventBus
from fugu_vibe.tools import FileTools, TerminalTool


class SequencedClient:
    def __init__(self, chunks_by_call: list[list[StreamChunk]]):
        self.chunks_by_call = chunks_by_call
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any):
        self.calls.append(kwargs)
        chunks = (
            self.chunks_by_call.pop(0)
            if self.chunks_by_call
            else [StreamChunk(type="content", content="done")]
        )
        for chunk in chunks:
            yield chunk


@pytest.mark.asyncio
async def test_agent_loop_allows_medium_tasks_by_default(tmp_path: Path) -> None:
    client = SequencedClient([[StreamChunk(type="content", content="done")]])
    registry = ToolRegistry(FileTools(tmp_path))
    loop = AgentLoop(client, registry, EventBus())

    assert DEFAULT_MAX_TOOL_ROUNDS == 10
    assert loop.max_tool_rounds == 10


@pytest.mark.asyncio
async def test_agent_loop_auto_runs_tests_after_file_edit(tmp_path: Path) -> None:
    (tmp_path / "test_sample.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    tool_call = {
        "call_id": "call-1",
        "name": "file_write",
        "arguments": '{"path":"notes.txt","content":"hello\\n"}',
    }
    client = SequencedClient(
        [
            [StreamChunk(type="tool_call", tool_call=tool_call)],
            [StreamChunk(type="content", content="finished")],
        ]
    )
    registry = ToolRegistry(
        FileTools(tmp_path, safety_mode="auto-edit"),
        terminal_tool=TerminalTool(
            tmp_path, enabled=True, safety_mode="auto-safe", timeout_seconds=10
        ),
    )
    loop = AgentLoop(client, registry, EventBus(), auto_test_after_edit=True)

    result = await loop.run([{"role": "user", "content": "write"}], "model", "high")

    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello\n"
    assert [call["name"] for call in result.tool_calls] == ["file_write", "run_test"]
    assert result.content == "finished"


@pytest.mark.asyncio
async def test_file_approval_preview_shows_overwrite_diff(tmp_path: Path) -> None:
    target = tmp_path / "notes.txt"
    target.write_text("before\n", encoding="utf-8")
    previews: list[str] = []

    async def approve(_name: str, _args: dict[str, Any], preview: str) -> bool:
        previews.append(preview)
        return True

    registry = ToolRegistry(FileTools(tmp_path, safety_mode="ask"), approval_callback=approve)
    result = await registry.dispatch("file_write", {"path": "notes.txt", "content": "after\n"})

    assert result["ok"] is True
    assert "--- a/notes.txt" in previews[0]
    assert "+++ b/notes.txt" in previews[0]
    assert "-before" in previews[0]
    assert "+after" in previews[0]
