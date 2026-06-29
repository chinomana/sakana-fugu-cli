"""Minimal Responses function-call execution loop."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from fugu_vibe.agent.registry import ToolRegistry
from fugu_vibe.core.event_bus import EventBus, EventType


class StreamingClient(Protocol):
    def send(self, **kwargs: Any): ...


DEFAULT_MAX_TOOL_ROUNDS = 10
DEFAULT_AUTO_TEST_COMMAND = "python -m pytest -q"
MUTATING_TOOLS = {"file_write", "file_edit", "file_delete", "file_mkdir"}
VALIDATION_TOOLS = {"run_test", "run_lint", "bash"}


@dataclass
class AgentLoopResult:
    """Final result from one agent turn."""

    content: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    rounds: int = 0


@dataclass
class AgentLoop:
    """Run a model turn, execute local function calls, and continue."""

    client: StreamingClient
    registry: ToolRegistry
    event_bus: EventBus
    max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS
    auto_test_after_edit: bool = True
    auto_test_command: str = DEFAULT_AUTO_TEST_COMMAND
    _auto_test_counter: int = field(default=0, init=False)

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
                if content:
                    if on_content:
                        on_content(content)
                    await self.event_bus.emit(
                        EventType.STREAM_CONTENT,
                        {"content": content},
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
                if normalized_name in VALIDATION_TOOLS:
                    mutation_without_validation = False
            if (
                mutation_without_validation
                and self.auto_test_after_edit
                and self.registry.has_tool("run_test")
            ):
                test_call, test_result = await self._run_auto_test()
                result.tool_calls.append(test_call)
                current_messages.extend(
                    [
                        self._tool_call_items([test_call], [])[0],
                        self._tool_result_message(test_call, test_result),
                    ]
                )
            current_messages.append(
                {
                    "role": "user",
                    "content": "Use the function_call_output results above to continue. If more workspace information is needed, call a different file tool. Do not repeat identical tool calls.",
                }
            )

        return result

    async def _run_auto_test(self) -> tuple[dict[str, Any], dict[str, Any]]:
        self._auto_test_counter += 1
        tool_call = {
            "type": "function_call",
            "call_id": f"auto-test-after-edit-{self._auto_test_counter}",
            "name": "run_test",
            "arguments": json.dumps({"command": self.auto_test_command}),
        }
        await self.event_bus.emit(
            EventType.STREAM_TOOL_CALL,
            {"tool_call": tool_call, "automatic": True},
            source="agent_loop",
        )
        tool_result = await self.registry.dispatch("run_test", {"command": self.auto_test_command})
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
        if not tool_result.get("ok"):
            return str(tool_result.get("error", "tool failed"))
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
