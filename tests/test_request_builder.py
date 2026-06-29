"""Tests for FuguRequestBuilder."""

import pytest

from fugu_vibe.api.request_builder import FuguRequestBuilder


class TestFuguRequestBuilder:
    """Test Fugu-specific request body construction."""

    def test_basic_request(self):
        builder = FuguRequestBuilder()
        body = builder.build(
            messages=[{"role": "user", "content": "Hello"}],
            model="fugu-ultra",
            effort="xhigh",
        )

        assert body["model"] == "fugu-ultra"
        assert body["reasoning"]["effort"] == "xhigh"
        assert body["stream"] is True
        assert body["max_output_tokens"] == 32768
        assert body["truncation"] == "auto"

    def test_reasoning_effort_normalization(self):
        builder = FuguRequestBuilder()

        # max → xhigh
        body = builder.build(
            messages=[{"role": "user", "content": "Test"}],
            model="fugu",
            effort="max",
        )
        assert body["reasoning"]["effort"] == "xhigh"

    def test_web_search_tool(self):
        builder = FuguRequestBuilder()
        body = builder.build(
            messages=[{"role": "user", "content": "Search"}],
            model="fugu",
            web_search=True,
        )

        assert "tools" in body
        assert body["tools"] == [{"type": "web_search"}]
        assert body["tool_choice"] == "auto"

    def test_unlimited_mode(self):
        builder = FuguRequestBuilder()
        body = builder.build(
            messages=[{"role": "user", "content": "Test"}],
            model="fugu",
            unlimited_mode=True,
        )

        assert body["instructions"] == ""

    def test_full_history_required(self):
        builder = FuguRequestBuilder()
        messages = [
            {"role": "user", "content": "First"},
            {"role": "assistant", "content": "Response"},
            {"role": "user", "content": "Second"},
        ]
        body = builder.build(
            messages=messages,
            model="fugu",
        )

        # Should send full messages array
        assert body["input"] == messages

    def test_invalid_effort_rejected(self):
        builder = FuguRequestBuilder()

        with pytest.raises(ValueError, match="Invalid effort"):
            builder.build(
                messages=[{"role": "user", "content": "Test"}],
                model="fugu",
                effort="invalid",
            )
