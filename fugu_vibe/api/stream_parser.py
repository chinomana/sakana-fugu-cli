"""SSE stream parser with orchestration signal detection."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import structlog

logger = structlog.get_logger()


@dataclass
class TokenUsage:
    """Token consumption snapshot."""

    input_tokens: int = 0
    output_tokens: int = 0
    orchestration_tokens: int = 0
    total_tokens: int = 0


@dataclass
class StreamChunk:
    """Parsed chunk from Fugu streaming response."""

    # Chunk classification
    type: str = ""  # content | reasoning | tool_call | token_usage | 
                    # routing_signal | worker_signal | done | error | heartbeat
    
    # Content
    content: str = ""
    tool_call: dict = field(default_factory=dict)
    output_item: dict = field(default_factory=dict)
    
    # Token tracking
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    
    # Orchestration inference (populated by OrchestrationAnalyzer)
    routing_confidence: float | None = None
    worker_id: str | None = None
    is_verification: bool = False
    
    # Metadata
    model: str = ""
    effort: str = ""
    finish_reason: str | None = None
    response_id: str | None = None
    elapsed_time: float = 0.0
    raw_timestamp: float = field(default_factory=time.monotonic)


class StreamParser:
    """
    Parses Server-Sent Events (SSE) from Fugu API streaming responses.
    
    Handles:
    - Content chunks (text output)
    - Reasoning chunks (model thinking)
    - Tool call chunks (function calls)
    - Usage chunks (token consumption with orchestration tokens)
    - Done/finish markers
    """

    def __init__(self):
        self._buffer = ""
        self._current_tool_call: dict | None = None
        self._response_items: dict[str, dict[str, Any]] = {}
        self._function_arguments: dict[str, str] = {}
        self._emitted_function_calls: set[str] = set()

    def parse_sse_chunk(self, data: str) -> StreamChunk | None:
        """
        Parse a single SSE data line into a StreamChunk.
        
        Returns None for heartbeats/keepalives.
        """
        try:
            event = json.loads(data)
        except json.JSONDecodeError:
            logger.debug("sse_parse_failed", data=data[:200])
            return None

        # Handle different event types
        event_type = event.get("type", "")

        typed_chunk = self._parse_typed_responses_event(event_type, event)
        if typed_chunk:
            return typed_chunk
        
        # OpenAI Responses API format
        if "output" in event:
            return self._parse_responses_api(event)
        
        # Chat Completions format  
        if "choices" in event:
            return self._parse_chat_completions(event)
            
        # Usage-only event
        if "usage" in event and not event_type:
            return self._parse_usage(event)
            
        # Done event
        if event_type == "done" or data.strip() == "[DONE]":
            return StreamChunk(type="done")
            
        return None

    def _parse_typed_responses_event(
        self,
        event_type: str,
        event: dict[str, Any],
    ) -> StreamChunk | None:
        """Parse streaming Responses API typed events."""
        if event_type in ("response.output_text.delta", "response.refusal.delta"):
            return StreamChunk(
                type="content",
                content=event.get("delta", ""),
                output_item=self._content_output_item(event),
            )

        if event_type == "response.reasoning_summary_text.delta":
            return StreamChunk(type="reasoning", content=event.get("delta", ""))

        if event_type == "response.output_item.added":
            item = event.get("item", {})
            item_id = item.get("id") or event.get("item_id")
            if item_id:
                self._response_items[item_id] = item
            return None

        if event_type == "response.function_call_arguments.delta":
            item_id = event.get("item_id")
            if item_id:
                self._function_arguments[item_id] = self._function_arguments.get(item_id, "") + event.get("delta", "")
            return None

        if event_type == "response.output_item.done":
            item = event.get("item", {})
            item_id = item.get("id") or event.get("item_id")
            if item_id and item_id in self._function_arguments:
                item = {**item, "arguments": self._function_arguments[item_id]}
            item_type = item.get("type", "")
            if item_type == "web_search_call":
                return StreamChunk(
                    type="tool_call",
                    tool_call={"name": "web_search", "arguments": item},
                    output_item=item,
                )
            if item_type == "function_call":
                call_key = item.get("call_id") or item_id
                if call_key in self._emitted_function_calls:
                    return None
                if call_key:
                    self._emitted_function_calls.add(call_key)
                return StreamChunk(
                    type="tool_call",
                    tool_call={
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", ""),
                        "call_id": item.get("call_id", ""),
                        "id": item.get("id", ""),
                    },
                    output_item=item,
                )

        if event_type == "response.function_call_arguments.done":
            item_id = event.get("item_id")
            cached_item = self._response_items.get(item_id or "", {})
            arguments = event.get("arguments", "") or self._function_arguments.get(item_id or "", "")
            output_item = {
                **cached_item,
                "type": "function_call",
                "name": event.get("name") or cached_item.get("name", ""),
                "arguments": arguments,
                "call_id": event.get("call_id") or cached_item.get("call_id", ""),
            }
            call_key = output_item.get("call_id") or item_id
            if call_key in self._emitted_function_calls:
                return None
            if call_key:
                self._emitted_function_calls.add(call_key)
            return StreamChunk(
                type="tool_call",
                tool_call={
                    "name": output_item.get("name", ""),
                    "arguments": output_item.get("arguments", ""),
                    "call_id": output_item.get("call_id", ""),
                    "id": output_item.get("id", ""),
                },
                output_item=output_item,
            )

        if event_type in ("response.completed", "response.incomplete"):
            response = event.get("response", {})
            chunk = StreamChunk(
                type="done",
                model=response.get("model", ""),
                response_id=response.get("id", ""),
                finish_reason=response.get("status", ""),
            )
            usage = response.get("usage", {})
            if usage:
                chunk.token_usage = self._usage_from_responses(usage)
            return chunk

        if event_type == "response.failed":
            response = event.get("response", {})
            error = response.get("error") or event.get("error") or {}
            return StreamChunk(
                type="error",
                content=str(error.get("message") or error),
                response_id=response.get("id", ""),
                finish_reason=response.get("status", "failed"),
            )

        return None

    def _parse_responses_api(self, event: dict[str, Any]) -> StreamChunk | None:
        """Parse OpenAI Responses API format."""
        chunk = StreamChunk()
        
        # Extract output items
        output = event.get("output", [])
        if isinstance(output, list):
            for item in output:
                item_type = item.get("type", "")
                
                if item_type == "message":
                    content = item.get("content", [])
                    for part in content:
                        if part.get("type") == "output_text":
                            chunk.type = "content"
                            chunk.content = part.get("text", "")
                            
                elif item_type == " reasoning":
                    chunk.type = "reasoning"
                    chunk.content = item.get("summary", [{}])[0].get("text", "")
                    
                elif item_type == "web_search_call":
                    chunk.type = "tool_call"
                    chunk.tool_call = {
                        "name": "web_search",
                        "arguments": item,
                    }
                    chunk.output_item = item
                    
                elif item_type == "function_call":
                    chunk.type = "tool_call"
                    chunk.tool_call = {
                        "name": item.get("name", ""),
                        "arguments": item.get("arguments", ""),
                        "call_id": item.get("call_id", ""),
                        "id": item.get("id", ""),
                    }
                    chunk.output_item = item
        
        # Extract usage with orchestration tokens
        usage = event.get("usage", {})
        if usage:
            chunk.type = chunk.type or "token_usage"
            chunk.token_usage = self._usage_from_responses(usage)
            
            # Extract routing confidence if available
            details = usage.get("details", {})
            if details:
                chunk.routing_confidence = details.get("routing_confidence")
        
        # Model info
        chunk.model = event.get("model", "")
        chunk.response_id = event.get("id", "")
        chunk.finish_reason = event.get("status", "")
        
        return chunk if chunk.type else None

    def _content_output_item(self, event: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "message",
            "id": event.get("item_id", ""),
            "role": "assistant",
            "content": [{"type": "output_text", "text": event.get("delta", "")}],
        }

    def _parse_chat_completions(self, event: dict[str, Any]) -> StreamChunk | None:
        """Parse Chat Completions streaming format."""
        chunk = StreamChunk()
        
        choices = event.get("choices", [])
        if not choices:
            # Usage-only chunk at end
            usage = event.get("usage", {})
            if usage:
                chunk.type = "token_usage"
                chunk.token_usage = TokenUsage(
                    input_tokens=usage.get("prompt_tokens", 0),
                    output_tokens=usage.get("completion_tokens", 0),
                    orchestration_tokens=usage.get("orchestration_tokens", 0),
                    total_tokens=usage.get("total_tokens", 0),
                )
                chunk.model = event.get("model", "")
                return chunk
            return None
        
        delta = choices[0].get("delta", {})
        
        # Content
        if delta.get("content"):
            chunk.type = "content"
            chunk.content = delta["content"]
            
        # Reasoning
        elif delta.get("reasoning"):
            chunk.type = "reasoning"
            chunk.content = delta["reasoning"]
            
        # Tool calls
        elif delta.get("tool_calls"):
            chunk.type = "tool_call"
            tc = delta["tool_calls"][0]
            chunk.tool_call = {
                "name": tc.get("function", {}).get("name", ""),
                "arguments": tc.get("function", {}).get("arguments", ""),
                "index": tc.get("index", 0),
            }
            
        # Finish
        elif choices[0].get("finish_reason"):
            chunk.type = "done"
            chunk.finish_reason = choices[0]["finish_reason"]
            
        chunk.model = event.get("model", "")
        
        return chunk if chunk.type else None

    def _parse_usage(self, event: dict[str, Any]) -> StreamChunk:
        """Parse standalone usage event."""
        usage = event["usage"]
        return StreamChunk(
            type="token_usage",
            token_usage=self._usage_from_responses(usage),
            model=event.get("model", ""),
        )

    def _usage_from_responses(self, usage: dict[str, Any]) -> TokenUsage:
        return TokenUsage(
            input_tokens=usage.get("input_tokens", usage.get("prompt_tokens", 0)),
            output_tokens=usage.get("output_tokens", usage.get("completion_tokens", 0)),
            orchestration_tokens=usage.get("orchestration_tokens", 0),
            total_tokens=usage.get("total_tokens", 0),
        )
