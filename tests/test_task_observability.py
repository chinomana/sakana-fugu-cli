"""Tests for task observability status and dashboard rendering."""

from __future__ import annotations

import asyncio
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from fugu_vibe.cli.commands.status import _format_tokens
from fugu_vibe.config import Config
from fugu_vibe.core.event_bus import EventBus
from fugu_vibe.core.task_manager import TaskManager, TaskStatus
from fugu_vibe.ui.components import TaskTree


class FakeClient:
    pass


@pytest.fixture
def config() -> Config:
    config = Config()
    config.tasks.use_git_worktree = False
    config.tasks.auto_merge = False
    return config


@pytest.mark.asyncio
async def test_task_status_exposes_observability_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    monkeypatch.chdir(tmp_path)
    manager = TaskManager(config, FakeClient(), EventBus(), run_scheduler=False)
    await manager.start()
    task = await manager.submit("observe", prompt="do work")
    task.status = TaskStatus.COMPLETED
    task.token_usage = {"input": 10, "output": 20, "orchestration": 5, "total": 35}
    task.metadata.update(
        {
            "rounds": 3,
            "tool_call_count": 2,
            "tool_calls": [{"name": "file_read"}, {"name": "run_test"}],
            "automatic_verification": {"compile": 1, "lint": 1, "test": 1, "total": 3},
            "orchestration": {
                "workers": 2,
                "verifications": 1,
                "routing_confidence": 0.75,
            },
        }
    )
    manager._persist_task(task)

    status = await manager.status(task.task_id)

    assert status["rounds"] == 3
    assert status["automatic_verification"] == {"compile": 1, "lint": 1, "test": 1, "total": 3}

    assert status["tool_call_count"] == 2
    assert status["token_usage"]["total"] == 35
    assert status["orchestration"] == {
        "workers": 2,
        "verifications": 1,
        "routing_confidence": 0.75,
    }
    await manager.close()


@pytest.mark.asyncio
async def test_task_status_reports_scheduled_waiting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    config: Config,
) -> None:
    monkeypatch.chdir(tmp_path)
    manager = TaskManager(config, FakeClient(), EventBus(), run_scheduler=False)
    await manager.start()
    active = await manager.submit("active", prompt="do work")
    waiting = await manager.submit("waiting", prompt="do work")
    manager._running_tasks = {
        active.task_id: asyncio.create_task(asyncio.sleep(0)),
        waiting.task_id: asyncio.create_task(asyncio.sleep(0)),
    }
    manager._active_task_ids = {active.task_id}

    status = await manager.status()

    assert status["running"] == 1
    assert status["scheduled_waiting"] == 1
    assert status["queued"] >= 1
    await asyncio.gather(*manager._running_tasks.values())
    await manager.close()


def test_format_tokens_supports_compact_and_detailed_output() -> None:
    tokens = {"input": 1000, "output": 2000, "orchestration": 300, "total": 3300}

    assert _format_tokens(tokens) == "3,300"
    assert _format_tokens(tokens, detailed=True) == "3,300 total (in 1,000 / out 2,000 / orch 300)"
    assert _format_tokens({}) == "-"


def test_task_tree_merges_updates_and_renders_observability_metrics() -> None:
    tree = TaskTree()
    tree.update_task({"task_id": "task-1", "name": "Observe", "status": "running", "model": "fugu"})
    tree.update_task(
        {
            "task_id": "task-1",
            "rounds": 2,
            "tool_call_count": 4,
            "token_usage": {"input": 10, "output": 20, "orchestration": 5},
            "orchestration": {"workers": 1, "verifications": 2, "routing_confidence": 0.8},
            "automatic_verification": {"compile": 1, "lint": 1, "test": 1, "total": 3},
        }
    )

    buffer = StringIO()
    console = Console(file=buffer, force_terminal=False, width=120)
    console.print(tree.render())
    rendered = buffer.getvalue()

    assert "Observe [fugu] · r2 · tools 4" in rendered
    assert "tokens 35" in rendered
    assert "workers 1, checks 2, confidence 80%" in rendered
    assert "auto checks 3 (compile 1, lint 1, test 1)" in rendered

