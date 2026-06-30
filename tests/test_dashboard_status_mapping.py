"""Tests for dashboard-friendly agent status mapping."""

from fugu_vibe.config import Config
from fugu_vibe.core.event_bus import Event, EventBus, EventType
from fugu_vibe.ui.dashboard import OrchestrationDashboard


def make_dashboard() -> OrchestrationDashboard:
    return OrchestrationDashboard(Config(), EventBus())


def test_dashboard_maps_file_edit_to_readable_action() -> None:
    dashboard = make_dashboard()

    dashboard._on_tool_call(
        Event(
            EventType.STREAM_TOOL_CALL,
            {
                "tool_call": {
                    "name": "file_edit",
                    "arguments": '{"path":"fugu_vibe/agent/loop.py"}',
                }
            },
        )
    )

    assert dashboard._agent_status == "editing"
    assert dashboard._current_tool == "file_edit"
    assert dashboard._current_action == "Editing fugu_vibe/agent/loop.py"
    assert dashboard._stream_content[-1] == "[tool] Editing fugu_vibe/agent/loop.py"


def test_dashboard_maps_automatic_py_compile_to_auto_check() -> None:
    dashboard = make_dashboard()

    dashboard._on_tool_call(
        Event(
            EventType.STREAM_TOOL_CALL,
            {
                "automatic": True,
                "tool_call": {
                    "name": "bash",
                    "arguments": '{"command":"python -m py_compile ./game.py"}',
                },
            },
        )
    )

    assert dashboard._agent_status == "compiling"
    assert dashboard._current_action == "Auto-check: Checking Python syntax: python -m py_compile ./game.py"
    assert dashboard._stream_content[-1] == (
        "[auto-check] Auto-check: Checking Python syntax: python -m py_compile ./game.py"
    )


def test_dashboard_maps_failed_validation_to_repairing_state() -> None:
    dashboard = make_dashboard()

    dashboard._on_tool_result(
        Event(
            EventType.STREAM_TOOL_RESULT,
            {
                "ok": False,
                "summary": "IndentationError: expected an indented block",
                "tool_call": {
                    "name": "bash",
                    "arguments": '{"command":"python -m py_compile ./game.py"}',
                },
            },
        )
    )

    assert dashboard._agent_status == "repairing"
    assert dashboard._current_action == "Validation failed; feeding the error back so the agent can fix it"
    assert dashboard._last_result_text == (
        "Python syntax check failed: IndentationError: expected an indented block"
    )


def test_dashboard_renders_automatic_verification_summary() -> None:
    dashboard = make_dashboard()

    dashboard._on_agent_round_end(
        Event(
            EventType.AGENT_ROUND_END,
            {
                "round": 1,
                "automatic_verification": {
                    "compile": 1,
                    "lint": 1,
                    "test": 1,
                    "total": 3,
                    "failed": 1,
                    "status": "failed",
                    "failures": [{"tool": "run_test", "summary": "1 failed"}],
                },
            },
        )
    )

    assert dashboard._verification_text() == "3 total · compile 1 · lint 1 · test 1 · 1 failed"

