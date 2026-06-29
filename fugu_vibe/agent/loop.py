"""Minimal Responses function-call execution loop."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any, Protocol

from fugu_vibe.agent.registry import ToolRegistry
from fugu_vibe.api.stream_parser import StreamChunk
from fugu_vibe.core.event_bus import EventBus, EventType


class StreamingClient(Protocol):
    def send(self, **kwargs: Any): ...


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
    max_tool_rounds: int = 4

    async def run(
        self,
        messages: list[dict[str, Any]],
        model: str,
        effort: str,
        web_search: bool = False,
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

            async for chunk in self.client.send(
                messages=current_messages,
                model=model,
                effort=effort,
                web_search=web_search,
                tools=local_tools,
            ):
                if chunk.type == "content":
                    content_parts.append(chunk.content)
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
                result.content += "\n[Stopped: maximum tool rounds reached]"
                return result

            new_tool_calls = [
                tool_call for tool_call in tool_calls
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
                current_messages.append(self._tool_result_message(tool_call, tool_result))
            current_messages.append(
                {
                    "role": "user",
                    "content": "Use the function_call_output results above to continue. If more workspace information is needed, call a different file tool. Do not repeat identical tool calls.",
                }
            )

        return result

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
