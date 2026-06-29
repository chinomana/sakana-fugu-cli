"""Tests for OrchestrationAnalyzer."""

import time

import pytest

from fugu_vibe.api.stream_parser import StreamChunk, TokenUsage
from fugu_vibe.core.event_bus import EventBus
from fugu_vibe.core.orchestration import OrchestrationAnalyzer, OrchestrationPhase


class TestOrchestrationAnalyzer:
    """Test orchestration pattern inference."""

    @pytest.fixture
    def analyzer(self):
        bus = EventBus()
        return OrchestrationAnalyzer(event_bus=bus)

    @pytest.mark.asyncio
    async def test_routing_detection(self, analyzer):
        """Test that initial delay triggers routing detection."""
        chunk = StreamChunk(
            type="content",
            content="Hello",
            elapsed_time=10.0,  # > 5s threshold
        )

        event = await analyzer.analyze_chunk(chunk)

        assert event is not None
        assert event.phase == OrchestrationPhase.ROUTING
        assert analyzer._routing_detected is True

    @pytest.mark.asyncio
    async def test_no_routing_for_fast_response(self, analyzer):
        """Test that fast responses don't trigger routing."""
        chunk = StreamChunk(
            type="content",
            content="Hello",
            elapsed_time=1.0,  # < 5s threshold
        )

        event = await analyzer.analyze_chunk(chunk)

        assert event is None
        assert analyzer._routing_detected is False

    @pytest.mark.asyncio
    async def test_verification_detection(self, analyzer):
        """Test verification keyword detection."""
        analyzer._first_token_time = time.monotonic()

        chunk = StreamChunk(
            type="content",
            content="Let me verify this result",
        )

        event = await analyzer.analyze_chunk(chunk)

        assert event is not None
        assert event.phase == OrchestrationPhase.VERIFYING

    @pytest.mark.asyncio
    async def test_token_usage_tracking(self, analyzer):
        """Test token usage accumulation."""
        chunk = StreamChunk(
            type="token_usage",
            token_usage=TokenUsage(
                input_tokens=100,
                output_tokens=200,
                orchestration_tokens=50,
            ),
        )

        await analyzer.analyze_chunk(chunk)

        assert analyzer.state.token_usage.input_tokens == 100
        assert analyzer.state.token_usage.output_tokens == 200
        assert analyzer.state.token_usage.orchestration_tokens == 50

    @pytest.mark.asyncio
    async def test_finalize(self, analyzer):
        """Test orchestration finalization."""
        event = await analyzer.finalize()

        assert event.phase == OrchestrationPhase.DONE
        assert "complete" in event.message.lower()
