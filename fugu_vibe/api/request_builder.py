"""Fugu-specific request body builder handling special parameters."""

from __future__ import annotations

from typing import Any, Literal

import structlog

from fugu_vibe.config import Config

logger = structlog.get_logger()


class FuguRequestBuilder:
    """
    Builds request bodies for Sakana Fugu API with special parameter handling.

    Key Fugu-specific behaviors:
    - reasoning.effort: high | xhigh (max is alias for xhigh)
    - tools: Supports built-in web_search
    - truncation: auto (default) | disabled
    - max_output_tokens: Up to 32768
    - temperature: Accepted but IGNORED by Fugu
    - parallel_tool_calls: Accepted but IGNORED (server forces true)
    - previous_response_id: NOT accepted (send full history)
    """

    # Fugu reasoning effort levels
    EFFORT_LEVELS = {"high", "xhigh", "max"}

    # Built-in tools available
    BUILTIN_TOOLS = {
        "web_search": {
            "type": "web_search",
        }
    }

    def __init__(self, config: Config | None = None):
        self.config = config or Config()

    def build(
        self,
        messages: list[dict[str, Any]],
        model: str,
        effort: Literal["high", "xhigh", "max"] = "xhigh",
        tools: list[dict] | None = None,
        web_search: bool = False,
        stream: bool = True,
        instructions: str | None = None,
        max_output_tokens: int = 32768,
        truncation: Literal["auto", "disabled"] = "auto",
        response_format: dict[str, Any] | None = None,
        store: bool = False,
        metadata: dict[str, str] | None = None,
        unlimited_mode: bool = False,
        custom_instructions: str | None = None,
        **extra: Any,
    ) -> dict[str, Any]:
        """
        Build a Fugu-compatible request body for Responses API.

        Args:
            messages: Conversation messages (full history required)
            model: Model slug (fugu | fugu-ultra)
            effort: Reasoning effort level
            tools: Additional tool definitions
            web_search: Enable built-in web search tool
            stream: Enable streaming response
            instructions: System/developer instructions
            max_output_tokens: Maximum output tokens (up to 32768)
            truncation: Token truncation mode
            response_format: JSON schema output format
            store: Persist conversation on server
            metadata: Custom metadata key-value pairs
            unlimited_mode: Override safety guardrails in instructions
            custom_instructions: Custom system prompt
            **extra: Additional parameters (logged but may be ignored)
        """
        # Normalize effort
        effort = "xhigh" if effort == "max" else effort
        if effort not in self.EFFORT_LEVELS:
            raise ValueError(f"Invalid effort: {effort}. Use: high, xhigh, max")

        # Build tool list
        tool_list: list[dict] = []
        if web_search:
            tool_list.append(self.BUILTIN_TOOLS["web_search"].copy())
        if tools:
            tool_list.extend(tools)

        # Handle instructions (system prompt)
        final_instructions = self._build_instructions(
            instructions=instructions,
            unlimited_mode=unlimited_mode,
            custom_instructions=custom_instructions,
        )

        input_payload = _responses_input_payload(messages)

        # Construct request body per Sakana Responses API spec
        body: dict[str, Any] = {
            "model": model,
            "input": input_payload,
            "instructions": final_instructions,
            "reasoning": {"effort": effort},
            "stream": stream,
            "max_output_tokens": max_output_tokens,
            "truncation": truncation,
        }

        # Add tools
        if tool_list:
            body["tools"] = tool_list
            body["tool_choice"] = "auto"

        # Add optional parameters
        if response_format:
            body["text.format"] = response_format
        if store:
            body["store"] = True
        if metadata:
            body["metadata"] = metadata

        # Log Fugu-specific parameter handling
        if extra.get("temperature") is not None:
            logger.warning(
                "temperature_ignored_by_fugu",
                value=extra["temperature"],
            )
        if extra.get("parallel_tool_calls") is not None:
            logger.warning(
                "parallel_tool_calls_ignored_by_fugu",
                value=extra["parallel_tool_calls"],
            )
        if extra:
            logger.debug("extra_parameters", params=list(extra.keys()))

        logger.debug(
            "request_built",
            model=model,
            effort=effort,
            tool_count=len(tool_list),
            web_search=web_search,
            unlimited_mode=unlimited_mode,
        )

        return body
    def _build_instructions(
        self,
        instructions: str | None,
        unlimited_mode: bool,
        custom_instructions: str | None,
    ) -> str:
        """Build system instructions with mode handling."""
        if unlimited_mode:
            # Minimal instructions, bypass safety guardrails
            return custom_instructions or ""

        if custom_instructions:
            return custom_instructions

        return instructions or ""

    def build_chat_completions(
        self,
        messages: list[dict[str, Any]],
        model: str = "fugu-ultra",
        effort: Literal["high", "xhigh", "max"] = "xhigh",
        web_search: bool = False,
        max_tokens: int = 32768,
        **extra: Any,
    ) -> dict[str, Any]:
        """
        Build request for Chat Completions API (fallback).
        Note: Responses API is preferred for full feature support.
        """
        effort = "xhigh" if effort == "max" else effort

        tools = []
        if web_search:
            tools.append({
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for information",
                    "parameters": {"type": "object", "properties": {}}
                }
            })

        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "reasoning": {"effort": effort},
            "stream": True,
            "max_tokens": max_tokens,
        }

        if tools:
            body["tools"] = tools

        return body


def _has_multimodal_content(messages: list[dict[str, Any]]) -> bool:
    return any(isinstance(message.get("content"), list) for message in messages)


def _responses_input_payload(messages: list[dict[str, Any]]) -> Any:
    if not messages:
        return ""
    if _can_send_single_text_input(messages):
        return messages[0]["content"]
    return messages


def _can_send_single_text_input(messages: list[dict[str, Any]]) -> bool:
    if len(messages) != 1:
        return False
    message = messages[0]
    return (
        set(message.keys()) >= {"role", "content"}
        and isinstance(message.get("content"), str)
        and not _has_multimodal_content(messages)
    )
