"""Low-level Sakana Fugu API client with stream resilience."""

from __future__ import annotations

import asyncio
import os
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Literal

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from fugu_vibe.config import Config
from fugu_vibe.api.request_builder import FuguRequestBuilder
from fugu_vibe.api.stream_parser import StreamChunk, StreamParser

logger = structlog.get_logger()


@dataclass
class TokenUsage:
    """Token consumption breakdown."""

    input_tokens: int = 0
    output_tokens: int = 0
    orchestration_tokens: int = 0
    total_tokens: int = 0

    def update(self, other: TokenUsage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.orchestration_tokens += other.orchestration_tokens
        self.total_tokens += other.total_tokens


@dataclass
class FuguResponse:
    """Unified response from Fugu API."""

    content: str = ""
    tool_calls: list[dict] = field(default_factory=list)
    reasoning: str = ""
    token_usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    effort: str = ""
    finish_reason: str | None = None
    response_id: str | None = None
    # Orchestration metadata (from Usage Details)
    routing_confidence: float | None = None


class FuguClient:
    """
    Async client for Sakana Fugu API with stream resilience.
    
    Handles:
    - Responses API (recommended) and Chat Completions API
    - 2-hour stream idle timeout (Sakana requirement)
    - Automatic stream reconnection
    - Token tracking (input/output/orchestration)
    - Built-in tool support (web_search)
    """

    # Sakana Fugu endpoints
    RESPONSES_ENDPOINT = "/responses"
    CHAT_ENDPOINT = "/chat/completions"
    
    # Fugu-specific model slugs
    MODELS = {
        "fugu": "fugu",
        "fugu-ultra": "fugu-ultra",
    }

    def __init__(self, config: Config | None = None):
        self.config = config or Config()
        self.api_config = self.config.api
        self.model_config = self.config.model
        
        # HTTP client with Sakana-recommended resilience
        timeout = httpx.Timeout(
            connect=30.0,
            read=float(self.api_config.stream_idle_timeout_ms) / 1000,
            write=30.0,
            pool=5.0,
        )
        self.client = httpx.AsyncClient(
            base_url=self.api_config.base_url,
            timeout=timeout,
            http2=True,
            headers={
                "Authorization": f"Bearer {self._get_api_key()}",
                "Content-Type": "application/json",
            },
        )
        self.parser = StreamParser()
        self._request_builder = FuguRequestBuilder(config)
        self._stream_retry_count = 0
        
        logger.info(
            "fugu_client_initialized",
            base_url=self.api_config.base_url,
            timeout=self.api_config.timeout,
        )

    def _get_api_key(self) -> str:
        """Get API key from config or environment."""
        key = self.api_config.api_key
        if not key:
            key = os.environ.get("SAKANA_API_KEY", "")
        if not key:
            raise ValueError(
                "SAKANA_API_KEY not set. "
                "Set via env var, config file, or --api-key flag."
            )
        return key

    async def send(
        self,
        messages: list[dict[str, Any]],
        model: str | None = None,
        effort: Literal["high", "xhigh", "max"] | None = None,
        tools: list[dict] | None = None,
        web_search: bool = False,
        stream: bool = True,
        instructions: str | None = None,
        max_output_tokens: int | None = None,
        **extra: Any,
    ) -> AsyncIterator[StreamChunk]:
        """
        Send a request to Fugu API with full streaming support.
        
        Yields StreamChunk objects for real-time processing.
        Handles automatic reconnection on stream drops.
        """
        model = model or self.model_config.default
        effort = effort or self.model_config.reasoning_effort
        
        # Build request body with Fugu-specific parameters
        request_body = self._request_builder.build(
            messages=messages,
            model=model,
            effort=effort,
            tools=tools,
            web_search=web_search,
            stream=stream,
            instructions=instructions,
            max_output_tokens=max_output_tokens or self.model_config.max_output_tokens,
            unlimited_mode=self.config.prompt.unlimited_mode,
            custom_instructions=self.config.prompt.custom_instructions,
            **extra,
        )

        endpoint = self.RESPONSES_ENDPOINT  # Preferred API
        
        logger.info(
            "fugu_request",
            model=model,
            effort=effort,
            message_count=len(messages),
            web_search=web_search,
        )

        start_time = time.monotonic()
        
        try:
            async for chunk in self._stream_with_resilience(endpoint, request_body):
                # Enrich chunk with timing for orchestration inference
                chunk.elapsed_time = time.monotonic() - start_time
                yield chunk
                
        except Exception as e:
            logger.error("fugu_request_failed", error=str(e), elapsed=time.monotonic() - start_time)
            raise

    async def _stream_with_resilience(
        self,
        endpoint: str,
        request_body: dict[str, Any],
    ) -> AsyncIterator[StreamChunk]:
        """
        Stream with Sakana-recommended resilience:
        - Reconnect dropped streams instead of failing
        - Retry transient HTTP failures
        - 2h idle timeout (don't drop slow turns)
        """
        max_stream_retries = self.api_config.stream_max_retries
        max_request_retries = self.api_config.request_max_retries
        
        for attempt in range(max_request_retries):
            try:
                async with self.client.stream(
                    "POST",
                    endpoint,
                    json=request_body,
                ) as response:
                    response.raise_for_status()
                    
                    async for line in response.aiter_lines():
                        if not line.strip():
                            continue
                            
                        if line.startswith("data: "):
                            data = line[6:]
                            if data == "[DONE]":
                                return
                                
                            chunk = self.parser.parse_sse_chunk(data)
                            if chunk:
                                yield chunk
                                
                        # Heartbeat: reset stream retry on activity
                        self._stream_retry_count = 0
                        
            except httpx.RemoteProtocolError as e:
                # Stream dropped - attempt reconnection
                self._stream_retry_count += 1
                if self._stream_retry_count <= max_stream_retries:
                    wait_time = min(2 ** self._stream_retry_count, 30)
                    logger.warning(
                        "stream_dropped_reconnecting",
                        attempt=self._stream_retry_count,
                        wait=wait_time,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                raise
                
            except httpx.HTTPStatusError as e:
                if e.response.status_code in (429, 502, 503, 504) and attempt < max_request_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(
                        "transient_error_retrying",
                        status=e.response.status_code,
                        attempt=attempt + 1,
                        wait=wait_time,
                    )
                    await asyncio.sleep(wait_time)
                    continue
                raise
                
            # Successful completion
            return

    async def chat_complete(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> FuguResponse:
        """
        Simplified interface: send request and return complete response.
        Aggregates streaming chunks into a single response.
        """
        response = FuguResponse()
        content_parts: list[str] = []
        
        async for chunk in self.send(messages, **kwargs):
            if chunk.type == "content":
                content_parts.append(chunk.content)
                response.content = "".join(content_parts)
            elif chunk.type == "tool_call":
                response.tool_calls.append(chunk.tool_call)
            elif chunk.type == "reasoning":
                response.reasoning += chunk.content
            elif chunk.type == "token_usage":
                response.token_usage.update(chunk.token_usage)
            elif chunk.type == "done":
                response.finish_reason = chunk.finish_reason
                response.model = chunk.model or response.model
                response.response_id = chunk.response_id
                
        return response

    async def get_models(self) -> list[dict[str, Any]]:
        """List available Fugu models."""
        response = await self.client.get("/models")
        response.raise_for_status()
        return response.json().get("data", [])

    async def close(self) -> None:
        """Close HTTP client."""
        await self.client.aclose()
        logger.info("fugu_client_closed")

    async def __aenter__(self) -> FuguClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
