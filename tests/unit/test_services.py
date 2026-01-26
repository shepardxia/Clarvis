"""Tests for services: weather, location, token_usage, and thinking_feed."""

import pytest
import responses
from pathlib import Path
from unittest.mock import patch

from clarvis.services.weather import fetch_weather, calculate_intensity
from clarvis.services.location import get_location, DEFAULT_LOCATION
from clarvis.services.thinking_feed import (
    parse_jsonl_line, extract_thinking_blocks, is_session_stop_event,
    SessionState, ThinkingBlock,
)


class TestWeather:
    def test_intensity_calculation(self):
        """Test weather intensity ranges."""
        assert calculate_intensity(0, 5, 0, 0) <= 0.1  # Calm
        assert calculate_intensity(95, 30, 10, 0) >= 0.7  # Storm
        assert 0 <= calculate_intensity(50, 50, 10, 5) <= 1  # Always valid range

    @responses.activate
    def test_fetch_weather(self, mock_weather_response):
        """Test weather API fetch."""
        responses.add(responses.GET, "https://api.open-meteo.com/v1/forecast",
                     json=mock_weather_response, status=200)
        weather = fetch_weather(37.7749, -122.4194)
        assert weather.temperature == 65.0


class TestLocation:
    @responses.activate
    @patch("clarvis.services.location._is_corelocation_available", return_value=False)
    def test_get_location_with_fallback(self, mock_coreloc):
        """Test location fetch and fallback."""
        responses.add(responses.GET, "http://ip-api.com/json/", json={
            "status": "success", "lat": 37.77, "lon": -122.42,
            "city": "SF", "timezone": "America/Los_Angeles"
        }, status=200)
        with patch("clarvis.services.location.get_hub_section", return_value=None):
            with patch("clarvis.services.location.write_hub_section"):
                lat, lon, _ = get_location()
        assert (lat, lon) == (37.77, -122.42)

        # Fallback on error
        responses.replace(responses.GET, "http://ip-api.com/json/", status=500)
        with patch("clarvis.services.location.get_hub_section", return_value=None):
            assert get_location() == DEFAULT_LOCATION


class TestThinkingFeed:
    def test_jsonl_parsing(self):
        """Test JSONL parsing."""
        assert parse_jsonl_line('{"type": "test"}') == {"type": "test"}
        assert parse_jsonl_line("") is None
        assert parse_jsonl_line("{bad}") is None

    def test_thinking_extraction(self, sample_jsonl_entry):
        """Test thinking block extraction."""
        blocks = extract_thinking_blocks(sample_jsonl_entry)
        assert len(blocks) == 1
        assert extract_thinking_blocks({"type": "user"}) == []

    def test_stop_event_detection(self):
        """Test session stop detection."""
        stop = {"type": "progress", "data": {"type": "hook_progress", "hookEvent": "Stop"}}
        assert is_session_stop_event(stop) is True
        assert is_session_stop_event({"type": "assistant"}) is False

    def test_session_state_thoughts(self):
        """Test session thought management."""
        session = SessionState(session_id="t", project="p", project_path="/p", file_path=Path("/tmp/t"))
        for i in range(60):
            session.add_thought(ThinkingBlock(text=f"T{i}", timestamp="t", session_id="t"), max_thoughts=50)
        assert len(session.thoughts) == 50
