"""Tests for AgentLoop audit hardening."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path
from typing import Any

import pytest

from fugu_vibe.agent.loop import DEFAULT_MAX_TOOL_ROUNDS, AgentLoop
from fugu_vibe.agent.registry import ToolRegistry
from fugu_vibe.api.stream_parser import StreamChunk
from fugu_vibe.core.event_bus import EventBus, EventType
from fugu_vibe.tools import FileTools, TerminalTool


class SequencedClient:
    def __init__(self, chunks_by_call: list[list[StreamChunk]]):
        self.chunks_by_call = chunks_by_call
        self.calls: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any):
        self.calls.append(copy.deepcopy(kwargs))
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
    assert result.automatic_verification == {"compile": 0, "lint": 0, "test": 1, "total": 1}
    assert result.content == "finished"
    assert {schema["name"] for schema in client.calls[0]["tools"]} >= {
        "file_write",
        "file_edit",
        "run_test",
    }


@pytest.mark.asyncio
async def test_agent_loop_auto_compiles_python_edits_and_repairs(tmp_path: Path) -> None:
    tool_calls = [
        {
            "call_id": "call-1",
            "name": "file_write",
            "arguments": '{"path":"game.py","content":"def broken():\\n"}',
        },
        {
            "call_id": "call-2",
            "name": "file_edit",
            "arguments": '{"path":"game.py","old_string":"def broken():\\n","new_string":"def broken():\\n    pass\\n"}',
        },
    ]
    client = SequencedClient(
        [
            [StreamChunk(type="tool_call", tool_call=tool_calls[0])],
            [StreamChunk(type="tool_call", tool_call=tool_calls[1])],
            [StreamChunk(type="content", content="fixed")],
        ]
    )
    registry = ToolRegistry(
        FileTools(tmp_path, safety_mode="auto-edit"),
        terminal_tool=TerminalTool(
            tmp_path, enabled=True, safety_mode="auto-safe", timeout_seconds=10
        ),
    )
    loop = AgentLoop(client, registry, EventBus(), auto_test_after_edit=False)

    result = await loop.run([{"role": "user", "content": "write python"}], "model", "high")

    assert (tmp_path / "game.py").read_text(encoding="utf-8") == "def broken():\n    pass\n"
    assert [call["name"] for call in result.tool_calls] == [
        "file_write",
        "bash",
        "file_edit",
        "bash",
        "run_lint",
    ]
    assert result.automatic_verification == {"compile": 2, "lint": 1, "test": 0, "total": 3}
    assert result.tool_calls[1]["arguments"] == '{"command": "python -m py_compile ./game.py"}'
    assert any("IndentationError" in message.get("output", "") for message in client.calls[1]["messages"])
    assert any("Automatic verification failed" in message.get("content", "") for message in client.calls[1]["messages"])
    assert result.content == "fixed"



@pytest.mark.asyncio
async def test_agent_loop_auto_lints_and_targets_existing_pytest_file(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def answer():\n    return 41\n", encoding="utf-8")
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text(
        "from app import answer\n\n\ndef test_answer():\n    assert answer() == 42\n",
        encoding="utf-8",
    )
    tool_call = {
        "call_id": "call-1",
        "name": "file_edit",
        "arguments": '{"path":"app.py","old_string":"return 41","new_string":"return 42"}',
    }
    client = SequencedClient(
        [
            [StreamChunk(type="tool_call", tool_call=tool_call)],
            [StreamChunk(type="content", content="verified")],
        ]
    )
    registry = ToolRegistry(
        FileTools(tmp_path, safety_mode="auto-edit"),
        terminal_tool=TerminalTool(
            tmp_path, enabled=True, safety_mode="auto-safe", timeout_seconds=10
        ),
    )
    loop = AgentLoop(client, registry, EventBus())

    result = await loop.run([{"role": "user", "content": "fix answer"}], "model", "high")

    assert [call["name"] for call in result.tool_calls] == ["file_edit", "bash", "run_lint", "run_test"]
    assert result.tool_calls[2]["arguments"] == '{"command": "ruff check ."}'
    assert result.tool_calls[3]["arguments"] == '{"command": "python -m pytest -q ./tests/test_app.py"}'
    assert result.automatic_verification == {"compile": 1, "lint": 1, "test": 1, "total": 3}
    assert result.content == "verified"


@pytest.mark.asyncio
async def test_agent_loop_emits_lifecycle_events(tmp_path: Path) -> None:
    tool_call = {
        "call_id": "call-1",
        "name": "file_write",
        "arguments": '{"path":"notes.txt","content":"hello\\n"}',
    }
    client = SequencedClient(
        [
            [StreamChunk(type="tool_call", tool_call=tool_call)],
            [StreamChunk(type="content", content="done")],
        ]
    )
    registry = ToolRegistry(FileTools(tmp_path, safety_mode="auto-edit"))
    event_bus = EventBus()
    await event_bus.start()
    seen: list[str] = []
    for event_type in EventType:
        event_bus.on(event_type, lambda event: seen.append(event.type.value))
    try:
        loop = AgentLoop(client, registry, event_bus, auto_test_after_edit=False)
        await loop.run([{"role": "user", "content": "write"}], "model", "high")
        await asyncio.sleep(0.05)
    finally:
        await event_bus.close()

    assert "agent:round_start" in seen
    assert "agent:round_end" in seen
    assert "agent:done" in seen
    assert "stream:tool_call" in seen
    assert "stream:tool_result" in seen

@pytest.mark.asyncio
async def test_agent_loop_passes_chunks_to_observer(tmp_path: Path) -> None:
    chunks = [
        StreamChunk(type="content", content="hello", elapsed_time=6.0),
        StreamChunk(type="token_usage"),
    ]
    client = SequencedClient([chunks])
    registry = ToolRegistry(FileTools(tmp_path))
    seen: list[str] = []

    async def observe(chunk: StreamChunk) -> None:
        seen.append(chunk.type)

    loop = AgentLoop(client, registry, EventBus())
    result = await loop.run(
        [{"role": "user", "content": "say hello"}],
        "model",
        "high",
        on_chunk=observe,
    )

    assert result.content == "hello"
    assert seen == ["content", "token_usage"]


@pytest.mark.asyncio
async def test_agent_loop_ignores_chunk_observer_errors(tmp_path: Path) -> None:
    chunks = [StreamChunk(type="content", content="hello", elapsed_time=6.0)]
    client = SequencedClient([chunks])
    registry = ToolRegistry(FileTools(tmp_path))

    def observe(_chunk: StreamChunk) -> None:
        raise RuntimeError("observer failed")

    loop = AgentLoop(client, registry, EventBus())
    result = await loop.run(
        [{"role": "user", "content": "say hello"}],
        "model",
        "high",
        on_chunk=observe,
    )

    assert result.content == "hello"





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
