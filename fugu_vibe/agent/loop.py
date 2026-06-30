"""Minimal Responses function-call execution loop."""

from __future__ import annotations

import inspect
import json
import shlex
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Protocol

import structlog

from fugu_vibe.agent.registry import ToolRegistry
from fugu_vibe.core.event_bus import EventBus, EventType

logger = structlog.get_logger()


class StreamingClient(Protocol):
    def send(self, **kwargs: Any): ...


DEFAULT_MAX_TOOL_ROUNDS = 10
DEFAULT_AUTO_TEST_COMMAND = "python -m pytest -q"
DEFAULT_AUTO_LINT_COMMAND = "ruff check ."
MUTATING_TOOLS = {"file_write", "file_edit", "file_delete", "file_mkdir"}
VALIDATION_TOOLS = {"run_test", "run_lint", "bash"}
PYTHON_SUFFIXES = {".py", ".pyw"}


@dataclass
class AgentLoopResult:
    """Final result from one agent turn."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0
    automatic_verification: dict[str, int] = field(default_factory=dict)


@dataclass
class AgentLoop:
    """Run a model turn, execute local function calls, and continue."""

    client: StreamingClient
    registry: ToolRegistry
    event_bus: EventBus
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    auto_test_after_edit: bool = True
    auto_test_command: str = DEFAULT_AUTO_TEST_COMMAND
    auto_compile_after_edit: bool = True
    auto_lint_after_edit: bool = True
    auto_lint_command: str = DEFAULT_AUTO_LINT_COMMAND
    _auto_test_counter: int = field(default=0, init=False)
    _auto_compile_counter: int = field(default=0, init=False)
    _auto_lint_counter: int = field(default=0, init=False)

    async def run(
        self,
        messages: list[dict[str, Any]],
        model: str,
        effort: str,
        web_search: bool = False,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
        on_content: Callable[[str], None] | None = None,
        on_tool_call: Callable[[dict[str, Any]], None] | None = None,
        on_chunk: Callable[[Any], Any] | None = None,
    ) -> AgentLoopResult:
        result = AgentLoopResult()
        current_messages = list(messages)
        executed_tools: set[tuple[str, str]] = set()
        allow_tools = True

        for round_index in range(self.max_tool_rounds + 1):
            result.rounds = round_index + 1
            content_parts: list[str] = []
            tool_calls: list[dict[str, Any]] = []
            output_items: list[dict[str, Any]] = []
            local_tools = self.registry.schemas() if allow_tools else None
            tool_names = [str(schema.get("name", "")) for schema in local_tools or []]
            await self.event_bus.emit(
                EventType.AGENT_ROUND_START,
                {
                    "round": round_index + 1,
                    "max_rounds": self.max_tool_rounds,
                    "tools_enabled": bool(local_tools),
                    "tool_count": len(tool_names),
                    "tool_names": tool_names,
                },
                source="agent_loop",
            )
            await self.event_bus.emit(
                EventType.STREAM_REASONING,
                {
                    "content": f"Starting agent round {round_index + 1} ({'tools enabled' if local_tools else 'tools disabled'})",
                },
                source="agent_loop",
            )

            async for chunk in self.client.send(
                messages=current_messages,
                model=model,
                effort=effort,
                web_search=web_search,
                tools=local_tools,
                instructions=instructions,
                max_output_tokens=max_output_tokens,
            ):
                if on_chunk:
                    try:
                        observer_result = on_chunk(chunk)
                        if inspect.isawaitable(observer_result):
                            await observer_result
                    except Exception as e:
                        logger.warning("chunk_observer_failed", chunk_type=chunk.type, error=str(e))
                if chunk.type == "content":
                    content_parts.append(chunk.content)
                    await self.event_bus.emit(
                        EventType.STREAM_CONTENT,
                        {"content": chunk.content, "provisional": True},
                        source="agent_loop",
                    )
                elif chunk.type == "reasoning":
                    await self.event_bus.emit(
                        EventType.STREAM_REASONING,
                        {"content": chunk.content},
                        source="agent_loop",
                    )
                elif chunk.type == "tool_call":
                    tool_calls.append(chunk.tool_call)
                    if chunk.output_item:
                        output_items.append(chunk.output_item)
                elif chunk.type == "token_usage":
                    await self.event_bus.emit(
                        EventType.STREAM_TOKEN_USAGE,
                        {
                            "input_tokens": chunk.token_usage.input_tokens,
                            "output_tokens": chunk.token_usage.output_tokens,
                            "orchestration_tokens": chunk.token_usage.orchestration_tokens,
                            "total_tokens": chunk.token_usage.total_tokens,
                        },
                        source="agent_loop",
                    )

            content = "".join(content_parts)
            if not tool_calls:
                result.content += content
                result.automatic_verification = self._verification_summary()
                if content:
                    if on_content:
                        on_content(content)
                    await self.event_bus.emit(
                        EventType.STREAM_CONTENT,
                        {"content": content},
                        source="agent_loop",
                    )
                await self.event_bus.emit(
                    EventType.AGENT_DONE,
                    {
                        "rounds": result.rounds,
                        "tool_calls": len(result.tool_calls),
                        "automatic_verification": result.automatic_verification,
                    },
                    source="agent_loop",
                )
                return result
            if round_index >= self.max_tool_rounds:
                message = "\n[Stopped: maximum tool rounds reached. Answering with the information gathered so far.]"
                result.content += message
                if on_content:
                    on_content(message)
                await self.event_bus.emit(
                    EventType.STREAM_CONTENT,
                    {"content": message},
                    source="agent_loop",
                )
                result.automatic_verification = self._verification_summary()
                await self.event_bus.emit(
                    EventType.AGENT_STOPPED,
                    {
                        "reason": "max_tool_rounds",
                        "rounds": result.rounds,
                        "automatic_verification": result.automatic_verification,
                    },
                    source="agent_loop",
                )
                return result

            new_tool_calls = [
                tool_call
                for tool_call in tool_calls
                if self._tool_signature(tool_call) not in executed_tools
            ]
            if not new_tool_calls:
                allow_tools = False
                current_messages.append(
                    {
                        "role": "user",
                        "content": "The last tool request repeated an already executed call. Answer now using the function_call_output results already available. Do not call tools again.",
                    }
                )
                continue

            if content:
                current_messages.append({"role": "assistant", "content": content})
            call_items = self._tool_call_items(new_tool_calls, output_items)
            current_messages.extend(call_items)
            mutation_without_validation = False
            mutated_paths: set[str] = set()
            for tool_call in new_tool_calls:
                executed_tools.add(self._tool_signature(tool_call))
                result.tool_calls.append(tool_call)
                if on_tool_call:
                    on_tool_call(tool_call)
                await self.event_bus.emit(
                    EventType.STREAM_TOOL_CALL,
                    {"tool_call": tool_call},
                    source="agent_loop",
                )
                tool_result = await self.registry.dispatch(
                    str(tool_call.get("name", "")),
                    tool_call.get("arguments", ""),
                )
                await self.event_bus.emit(
                    EventType.STREAM_TOOL_RESULT,
                    {
                        "tool_call": tool_call,
                        "ok": bool(tool_result.get("ok")),
                        "summary": self._tool_result_summary(tool_result),
                    },
                    source="agent_loop",
                )
                current_messages.append(self._tool_result_message(tool_call, tool_result))
                normalized_name = str(tool_call.get("name", "")).replace(".", "_")
                if tool_result.get("ok") and normalized_name in MUTATING_TOOLS:
                    mutation_without_validation = True
                    self._collect_mutated_path(tool_result, mutated_paths)
                if normalized_name in VALIDATION_TOOLS:
                    mutation_without_validation = False
            if mutation_without_validation:
                verification_items = await self._run_auto_verification(mutated_paths)
                verification_failed = False
                for verification_call, verification_result in verification_items:
                    result.tool_calls.append(verification_call)
                    verification_failed = verification_failed or not verification_result.get("ok")
                    current_messages.extend(
                        [
                            self._tool_call_items([verification_call], [])[0],
                            self._tool_result_message(verification_call, verification_result),
                        ]
                    )
                result.automatic_verification = self._verification_summary()
                if verification_failed:
                    current_messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Automatic verification failed. Inspect the failure output, "
                                "apply a repair with file tools, and run verification again before finalizing."
                            ),
                        }
                    )
            await self.event_bus.emit(
                EventType.AGENT_ROUND_END,
                {
                    "round": round_index + 1,
                    "tool_calls": len(new_tool_calls),
                    "mutated_paths": sorted(mutated_paths),
                    "automatic_verification": self._verification_summary(),
                },
                source="agent_loop",
            )
            current_messages.append(
                {
                    "role": "user",
                    "content": "Use the function_call_output results above to continue. If more workspace information is needed, call a different file tool. Do not repeat identical tool calls.",
                }
            )

        return result

    async def _run_auto_verification(
        self,
        mutated_paths: set[str],
    ) -> list[tuple[dict[str, Any], dict[str, Any]]]:
        verification_items: list[tuple[dict[str, Any], dict[str, Any]]] = []
        if self.auto_compile_after_edit and self.registry.has_tool("bash"):
            compile_command = self._python_compile_command(mutated_paths)
            if compile_command:
                compile_item = await self._run_automatic_tool(
                    "bash",
                    {"command": compile_command},
                    "auto-py-compile-after-edit",
                )
                verification_items.append(compile_item)
                if not compile_item[1].get("ok"):
                    return verification_items
        if self.auto_lint_after_edit and self.registry.has_tool("run_lint"):
            lint_command = self._auto_lint_command(mutated_paths)
            if lint_command:
                verification_items.append(
                    await self._run_automatic_tool(
                        "run_lint",
                        {"command": lint_command},
                        "auto-lint-after-edit",
                    )
                )
        if self.auto_test_after_edit and self.registry.has_tool("run_test"):
            test_command = self._auto_test_command(mutated_paths)
            if test_command:
                verification_items.append(
                    await self._run_automatic_tool(
                        "run_test",
                        {"command": test_command},
                        "auto-test-after-edit",
                    )
                )
        return verification_items

    async def _run_automatic_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        call_prefix: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        if name == "run_test":
            self._auto_test_counter += 1
            counter = self._auto_test_counter
        elif name == "run_lint":
            self._auto_lint_counter += 1
            counter = self._auto_lint_counter
        else:
            self._auto_compile_counter += 1
            counter = self._auto_compile_counter
        tool_call = {
            "type": "function_call",
            "call_id": f"{call_prefix}-{counter}",
            "name": name,
            "arguments": json.dumps(arguments),
        }
        await self.event_bus.emit(
            EventType.STREAM_TOOL_CALL,
            {"tool_call": tool_call, "automatic": True},
            source="agent_loop",
        )
        tool_result = await self.registry.dispatch(name, arguments)
        await self.event_bus.emit(
            EventType.STREAM_TOOL_RESULT,
            {
                "tool_call": tool_call,
                "ok": bool(tool_result.get("ok")),
                "summary": self._tool_result_summary(tool_result),
                "automatic": True,
            },
            source="agent_loop",
        )
        return tool_call, tool_result

    def _collect_mutated_path(self, tool_result: dict[str, Any], mutated_paths: set[str]) -> None:
        if tool_result.get("deleted"):
            return
        path = tool_result.get("path")
        if isinstance(path, str) and path:
            mutated_paths.add(path)

    def _python_compile_command(self, mutated_paths: set[str]) -> str | None:
        python_paths = sorted(
            path
            for path in mutated_paths
            if PurePosixPath(path).suffix.lower() in PYTHON_SUFFIXES
        )
        if not python_paths:
            return None
        quoted_paths = " ".join(shlex.quote(f"./{path}") for path in python_paths)
        return f"python -m py_compile {quoted_paths}"

    def _auto_lint_command(self, mutated_paths: set[str]) -> str | None:
        """Return a lint command when edited files are likely lintable."""
        if not self.auto_lint_command.strip():
            return None
        if not mutated_paths or any(
            PurePosixPath(path).suffix.lower() in PYTHON_SUFFIXES for path in mutated_paths
        ):
            return self.auto_lint_command
        return None

    def _auto_test_command(self, mutated_paths: set[str]) -> str | None:
        """Return the test command, narrowed to colocated pytest files when obvious."""
        command = self.auto_test_command.strip()
        if not command:
            return None
        if not self._is_default_pytest_command(command):
            return command
        candidate_tests = self._candidate_pytest_files(mutated_paths)
        existing_tests = [
            path for path in candidate_tests if (self.registry.file_tools.workspace / path).is_file()
        ]
        if existing_tests:
            quoted = " ".join(shlex.quote(f"./{path}") for path in existing_tests)
            return f"python -m pytest -q {quoted}"
        return command

    def _candidate_pytest_files(self, mutated_paths: set[str]) -> list[str]:
        candidates: list[str] = []
        for path in sorted(mutated_paths):
            pure_path = PurePosixPath(path)
            if pure_path.suffix.lower() not in PYTHON_SUFFIXES:
                continue
            if pure_path.name.startswith("test_") or pure_path.name.endswith("_test.py"):
                candidates.append(path)
                continue
            candidates.extend(
                [
                    str(PurePosixPath("tests") / f"test_{pure_path.name}"),
                    str(pure_path.parent / "tests" / f"test_{pure_path.name}"),
                    str(pure_path.with_name(f"test_{pure_path.name}")),
                ]
            )
        return list(dict.fromkeys(candidates))

    def _is_default_pytest_command(self, command: str) -> bool:
        return command in {"python -m pytest -q", "pytest -q", "python -m pytest", "pytest"}

    def _verification_summary(self) -> dict[str, int]:
        """Return automatic verification counters for events and task metadata."""
        total = self._auto_compile_counter + self._auto_lint_counter + self._auto_test_counter
        return {
            "compile": self._auto_compile_counter,
            "lint": self._auto_lint_counter,
            "test": self._auto_test_counter,
            "total": total,
        }

    def _tool_result_message(
        self,
        tool_call: dict[str, Any],
        tool_result: dict[str, Any],
    ) -> dict[str, Any]:
        call_id = tool_call.get("call_id") or tool_call.get("id") or ""
        return {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(tool_result, ensure_ascii=False),
        }

    def _tool_call_items(
        self,
        tool_calls: list[dict[str, Any]],
        output_items: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        by_call_id = {item.get("call_id"): item for item in output_items if item.get("call_id")}
        items: list[dict[str, Any]] = []
        for tool_call in tool_calls:
            call_id = tool_call.get("call_id") or tool_call.get("id") or ""
            item = by_call_id.get(call_id)
            if item:
                items.append(item)
                continue
            items.append(
                {
                    "type": "function_call",
                    "call_id": call_id,
                    "name": tool_call.get("name", ""),
                    "arguments": tool_call.get("arguments", ""),
                }
            )
        return items

    def _tool_signature(self, tool_call: dict[str, Any]) -> tuple[str, str]:
        name = str(tool_call.get("name", "")).replace(".", "_")
        arguments = tool_call.get("arguments", "")
        try:
            parsed = json.loads(arguments) if isinstance(arguments, str) else arguments
        except json.JSONDecodeError:
            parsed = arguments
        return name, json.dumps(parsed, sort_keys=True, ensure_ascii=False)

    def _tool_result_summary(self, tool_result: dict[str, Any]) -> str:
        if "summary" in tool_result and isinstance(tool_result["summary"], dict):
            summary = tool_result["summary"]
            if summary.get("status"):
                return str(summary["status"])
        if not tool_result.get("ok"):
            if tool_result.get("error"):
                return str(tool_result["error"])
            output = str(tool_result.get("stderr") or tool_result.get("stdout") or "").strip()
            if output:
                return output.splitlines()[-1][:240]
            return "tool failed"
        if "files" in tool_result:
            return f"{tool_result.get('count', len(tool_result.get('files', [])))} files"
        if "matches" in tool_result:
            return f"{tool_result.get('count', len(tool_result.get('matches', [])))} matches"
        if "content" in tool_result:
            content = str(tool_result.get("content", ""))
            return f"read {len(content)} chars from {tool_result.get('path', 'file')}"
        if "bytes" in tool_result:
            return f"wrote {tool_result.get('bytes')} bytes to {tool_result.get('path', 'file')}"
        if "path" in tool_result:
            return f"created {tool_result.get('path')}"
        return "ok"
