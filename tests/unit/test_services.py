"""Tests for services: weather, location, token_usage, and thinking_feed."""

import pytest
import responses
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch

from clarvis.services.weather import fetch_weather, calculate_intensity, weather_code_to_desc
from clarvis.services.location import get_location, get_cached_timezone, DEFAULT_LOCATION
from clarvis.services.token_usage import TokenUsageService
from clarvis.services.thinking_feed import (
    parse_jsonl_line, extract_thinking_blocks, is_session_stop_event,
    extract_project_from_path, SessionState, SessionStatus, ThinkingBlock,
)


class TestWeather:
    def test_weather_code_descriptions(self):
        """Test weather code to description mapping."""
        assert weather_code_to_desc(0) == "Clear"
        assert weather_code_to_desc(63) == "Rain"
        assert weather_code_to_desc(75) == "Heavy Snow"
        assert weather_code_to_desc(999) == "Unknown"

    def test_intensity_calculation(self):
        """Test weather intensity calculation."""
        # Calm weather = low intensity
        assert calculate_intensity(0, 5, 0, 0) <= 0.1

        # Thunderstorm = high intensity
        assert calculate_intensity(95, 30, 10, 0) >= 0.7

        # Wind increases intensity
        assert calculate_intensity(0, 40, 0, 0) > calculate_intensity(0, 5, 0, 0)

        # Always in valid range
        for code, wind, precip, snow in [(0, 0, 0, 0), (95, 100, 50, 20)]:
            assert 0 <= calculate_intensity(code, wind, precip, snow) <= 1

    @responses.activate
    def test_fetch_weather(self, mock_weather_response, mock_weather_response_rain):
        """Test fetching weather from API."""
        responses.add(responses.GET, "https://api.open-meteo.com/v1/forecast",
                     json=mock_weather_response, status=200)
        weather = fetch_weather(37.7749, -122.4194)
        assert weather.temperature == 65.0
        assert weather.description == "Overcast"

        responses.replace(responses.GET, "https://api.open-meteo.com/v1/forecast",
                         json=mock_weather_response_rain, status=200)
        weather = fetch_weather(37.7749, -122.4194)
        assert weather.description == "Rain"
        assert weather.intensity > 0.3

    @responses.activate
    def test_fetch_weather_error(self):
        """Test weather API error handling."""
        responses.add(responses.GET, "https://api.open-meteo.com/v1/forecast", status=500)
        with pytest.raises(Exception):
            fetch_weather(37.7749, -122.4194)


class TestLocation:
    @responses.activate
    @patch("clarvis.services.location._is_corelocation_available", return_value=False)
    def test_get_location(self, mock_coreloc):
        """Test location retrieval from IP API."""
        responses.add(responses.GET, "http://ip-api.com/json/", json={
            "status": "success", "lat": 37.7749, "lon": -122.4194,
            "city": "San Francisco", "timezone": "America/Los_Angeles"
        }, status=200)
        with patch("clarvis.services.location.get_hub_section", return_value=None):
            with patch("clarvis.services.location.write_hub_section"):
                lat, lon, city = get_location()
        assert (lat, lon) == (37.7749, -122.4194)

        # API failure returns default
        responses.replace(responses.GET, "http://ip-api.com/json/", status=500)
        with patch("clarvis.services.location.get_hub_section", return_value=None):
            assert get_location() == DEFAULT_LOCATION

    def test_cached_timezone(self):
        """Test timezone caching."""
        with patch("clarvis.services.location.get_hub_section", return_value={"timezone": "America/Los_Angeles"}):
            assert get_cached_timezone() == "America/Los_Angeles"
        with patch("clarvis.services.location.get_hub_section", return_value=None):
            assert get_cached_timezone() is None


class TestTokenUsage:
    def test_service_basics(self):
        """Test TokenUsageService initialization and limits."""
        service = TokenUsageService()
        assert service.poll_interval == 120
        assert TokenUsageService(poll_interval=5).poll_interval == 10  # Minimum enforced

    @patch("clarvis.services.token_usage.subprocess.run")
    def test_keychain_fetch(self, mock_run):
        """Test fetching token from keychain."""
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = b'{"claudeAiOauth":{"accessToken":"test-token"}}'
        assert TokenUsageService()._fetch_from_keychain() == "test-token"

        mock_run.side_effect = Exception("Keychain error")
        assert TokenUsageService()._fetch_from_keychain() is None

    def test_usage_data(self):
        """Test usage data retrieval and staleness."""
        service = TokenUsageService(poll_interval=10)
        service._usage_data = {"five_hour": {"utilization": 6.0}, "seven_day": {"utilization": 35.0}}
        result = service.get_usage()
        assert "five_hour" in result
        assert "is_stale" in result

        # Test staleness
        service._last_updated = datetime.now(timezone.utc) - timedelta(seconds=21)
        assert service.get_usage().get("is_stale") is True


class TestThinkingFeed:
    def test_jsonl_parsing(self):
        """Test JSONL line parsing."""
        assert parse_jsonl_line('{"type": "assistant"}') == {"type": "assistant"}
        assert parse_jsonl_line("") is None
        assert parse_jsonl_line("   ") is None
        assert parse_jsonl_line("{invalid}") is None

    def test_thinking_block_extraction(self, sample_jsonl_entry):
        """Test extracting thinking blocks from JSONL entries."""
        blocks = extract_thinking_blocks(sample_jsonl_entry)
        assert len(blocks) == 1
        assert blocks[0].text == "Let me analyze this problem..."

        # Skip non-assistant and sidechain
        assert extract_thinking_blocks({"type": "user"}) == []
        sample_jsonl_entry["isSidechain"] = True
        assert extract_thinking_blocks(sample_jsonl_entry) == []

    def test_multiple_and_empty_blocks(self):
        """Test multiple thinking blocks and empty filtering."""
        entry = {
            "type": "assistant", "sessionId": "s", "timestamp": "t", "uuid": "u",
            "message": {"content": [
                {"type": "thinking", "thinking": ""},
                {"type": "thinking", "thinking": "First"},
                {"type": "thinking", "thinking": "Second"},
            ]}
        }
        blocks = extract_thinking_blocks(entry)
        assert len(blocks) == 2  # Empty one filtered

    def test_session_stop_detection(self):
        """Test stop event detection."""
        stop = {"type": "progress", "data": {"type": "hook_progress", "hookEvent": "Stop"}}
        non_stop = {"type": "progress", "data": {"type": "hook_progress", "hookEvent": "PreToolUse"}}
        assert is_session_stop_event(stop) is True
        assert is_session_stop_event(non_stop) is False
        assert is_session_stop_event({"type": "assistant"}) is False

    def test_project_extraction(self):
        """Test extracting project name from path."""
        path = Path("/Users/user/.claude/projects/-Users-user-myproject/session.jsonl")
        name, _ = extract_project_from_path(path)
        assert name == "myproject"

    def test_session_state(self):
        """Test SessionState management."""
        session = SessionState(session_id="t", project="p", project_path="/p", file_path=Path("/tmp/t"))

        # Add thoughts and check status
        session.add_thought(ThinkingBlock(text="thought", timestamp="t", session_id="t"))
        assert len(session.thoughts) == 1
        assert session.status == SessionStatus.ACTIVE

        # Max thoughts limit
        for i in range(60):
            session.add_thought(ThinkingBlock(text=f"T{i}", timestamp="t", session_id="t"), max_thoughts=50)
        assert len(session.thoughts) == 50

        # Get recent
        assert len(session.get_recent_thoughts(limit=3)) == 3

    def test_thinking_block_dataclass(self):
        """Test ThinkingBlock fields."""
        block = ThinkingBlock(text="t", timestamp="t", session_id="s")
        assert block.message_id == ""
        block2 = ThinkingBlock(text="t", timestamp="ts", session_id="s", message_id="m")
        assert block2.message_id == "m"

    def test_session_status_enum(self):
        """Test SessionStatus values."""
        assert SessionStatus.ACTIVE.value == "active"
        assert SessionStatus.IDLE.value == "idle"
        assert SessionStatus.ENDED.value == "ended"
