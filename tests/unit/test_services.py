"""Tests for services: weather, location, token_usage, and thinking_feed."""

import json
import time
import pytest
import responses
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from clarvis.services.weather import (
    fetch_weather,
    calculate_intensity,
    weather_code_to_desc,
)
from clarvis.services.location import get_location, get_cached_timezone, DEFAULT_LOCATION
from clarvis.services.token_usage import TokenUsageService
from clarvis.services.thinking_feed import (
    parse_jsonl_line,
    extract_thinking_blocks,
    is_session_stop_event,
    extract_project_from_path,
    SessionState,
    SessionStatus,
    ThinkingBlock,
)


# =============================================================================
# Weather Tests
# =============================================================================


class TestWeatherCode:
    """Tests for weather code utilities."""

    def test_code_to_desc_clear(self):
        assert weather_code_to_desc(0) == "Clear"

    def test_code_to_desc_rain(self):
        assert weather_code_to_desc(63) == "Rain"

    def test_code_to_desc_heavy_snow(self):
        assert weather_code_to_desc(75) == "Heavy Snow"

    def test_code_to_desc_unknown(self):
        assert weather_code_to_desc(999) == "Unknown"


class TestWeatherIntensity:
    """Tests for weather intensity calculation."""

    def test_clear_calm_low_intensity(self):
        intensity = calculate_intensity(weather_code=0, wind_speed=5, precipitation=0, snowfall=0)
        assert 0 <= intensity <= 0.1

    def test_thunderstorm_high_intensity(self):
        intensity = calculate_intensity(weather_code=95, wind_speed=30, precipitation=10, snowfall=0)
        assert intensity >= 0.7

    def test_intensity_always_in_range(self):
        for code, wind, precip, snow in [(0, 0, 0, 0), (95, 100, 50, 20), (63, 25, 5, 0)]:
            intensity = calculate_intensity(code, wind, precip, snow)
            assert 0 <= intensity <= 1

    def test_wind_increases_intensity(self):
        assert calculate_intensity(0, 40, 0, 0) > calculate_intensity(0, 5, 0, 0)


class TestFetchWeather:
    """Tests for fetch_weather with mocked API."""

    @responses.activate
    def test_fetch_success(self, mock_weather_response):
        responses.add(responses.GET, "https://api.open-meteo.com/v1/forecast",
                     json=mock_weather_response, status=200)
        weather = fetch_weather(37.7749, -122.4194)
        assert weather.temperature == 65.0
        assert weather.description == "Overcast"

    @responses.activate
    def test_fetch_rain(self, mock_weather_response_rain):
        responses.add(responses.GET, "https://api.open-meteo.com/v1/forecast",
                     json=mock_weather_response_rain, status=200)
        weather = fetch_weather(37.7749, -122.4194)
        assert weather.description == "Rain"
        assert weather.intensity > 0.3

    @responses.activate
    def test_fetch_api_error(self):
        responses.add(responses.GET, "https://api.open-meteo.com/v1/forecast", status=500)
        with pytest.raises(Exception):
            fetch_weather(37.7749, -122.4194)


# =============================================================================
# Location Tests
# =============================================================================


class TestLocation:
    """Tests for location retrieval."""

    @responses.activate
    @patch("clarvis.services.location._is_corelocation_available", return_value=False)
    def test_get_location_from_ip(self, mock_coreloc):
        responses.add(responses.GET, "http://ip-api.com/json/", json={
            "status": "success", "lat": 37.7749, "lon": -122.4194,
            "city": "San Francisco", "timezone": "America/Los_Angeles"
        }, status=200)
        with patch("clarvis.services.location.get_hub_section", return_value=None):
            with patch("clarvis.services.location.write_hub_section"):
                lat, lon, city = get_location()
        assert (lat, lon) == (37.7749, -122.4194)

    @responses.activate
    @patch("clarvis.services.location._is_corelocation_available", return_value=False)
    def test_get_location_api_failure(self, mock_coreloc):
        responses.add(responses.GET, "http://ip-api.com/json/", status=500)
        with patch("clarvis.services.location.get_hub_section", return_value=None):
            assert get_location() == DEFAULT_LOCATION


class TestTimezone:
    """Tests for timezone caching."""

    def test_get_from_cache(self):
        cached = {"timezone": "America/Los_Angeles"}
        with patch("clarvis.services.location.get_hub_section", return_value=cached):
            assert get_cached_timezone() == "America/Los_Angeles"

    def test_get_no_cache(self):
        with patch("clarvis.services.location.get_hub_section", return_value=None):
            assert get_cached_timezone() is None


# =============================================================================
# Token Usage Tests
# =============================================================================


class TestTokenUsageService:
    """Tests for TokenUsageService."""

    def test_initialization(self):
        service = TokenUsageService()
        assert service.poll_interval == 120

    def test_minimum_poll_interval(self):
        assert TokenUsageService(poll_interval=5).poll_interval == 10

    @patch("clarvis.services.token_usage.subprocess.run")
    def test_fetch_from_keychain_success(self, mock_run):
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = b'{"claudeAiOauth":{"accessToken":"test-token"}}'
        assert TokenUsageService()._fetch_from_keychain() == "test-token"

    @patch("clarvis.services.token_usage.subprocess.run")
    def test_fetch_from_keychain_failure(self, mock_run):
        mock_run.side_effect = Exception("Keychain error")
        assert TokenUsageService()._fetch_from_keychain() is None

    @patch("clarvis.services.token_usage.requests.get")
    def test_fetch_usage_success(self, mock_get):
        mock_get.return_value.json.return_value = {
            "five_hour": {"utilization": 6.0}, "seven_day": {"utilization": 35.0}
        }
        service = TokenUsageService()
        service._token = "test-token"
        result = service._fetch_usage()
        assert "five_hour" in result

    def test_get_usage_cached(self):
        service = TokenUsageService()
        service._usage_data = {"five_hour": {"utilization": 6.0}, "seven_day": {"utilization": 35.0}}
        result = service.get_usage()
        assert "five_hour" in result
        assert "is_stale" in result

    def test_staleness_calculation(self):
        service = TokenUsageService(poll_interval=10)
        service._usage_data = {"five_hour": {"utilization": 5.0}}
        service._last_updated = datetime.now(timezone.utc) - timedelta(seconds=21)
        assert service.get_usage().get("is_stale") is True


# =============================================================================
# Thinking Feed Tests
# =============================================================================


class TestParseJsonl:
    """Tests for JSONL parsing."""

    def test_valid_json(self):
        assert parse_jsonl_line('{"type": "assistant"}') == {"type": "assistant"}

    def test_empty_line(self):
        assert parse_jsonl_line("") is None
        assert parse_jsonl_line("   ") is None

    def test_invalid_json(self):
        assert parse_jsonl_line("{invalid}") is None


class TestExtractThinkingBlocks:
    """Tests for thinking block extraction."""

    def test_extract_from_assistant(self, sample_jsonl_entry):
        blocks = extract_thinking_blocks(sample_jsonl_entry)
        assert len(blocks) == 1
        assert blocks[0].text == "Let me analyze this problem..."

    def test_skip_non_assistant(self):
        assert extract_thinking_blocks({"type": "user"}) == []

    def test_skip_sidechain(self, sample_jsonl_entry):
        sample_jsonl_entry["isSidechain"] = True
        assert extract_thinking_blocks(sample_jsonl_entry) == []

    def test_multiple_blocks(self):
        entry = {
            "type": "assistant", "sessionId": "s", "timestamp": "t", "uuid": "u",
            "message": {"content": [
                {"type": "thinking", "thinking": "First"},
                {"type": "thinking", "thinking": "Second"},
            ]}
        }
        blocks = extract_thinking_blocks(entry)
        assert len(blocks) == 2

    def test_skip_empty_thinking(self):
        entry = {
            "type": "assistant", "sessionId": "s", "timestamp": "t", "uuid": "u",
            "message": {"content": [
                {"type": "thinking", "thinking": ""},
                {"type": "thinking", "thinking": "Has content"},
            ]}
        }
        assert len(extract_thinking_blocks(entry)) == 1


class TestSessionStopEvent:
    """Tests for stop event detection."""

    def test_stop_event(self):
        entry = {"type": "progress", "data": {"type": "hook_progress", "hookEvent": "Stop"}}
        assert is_session_stop_event(entry) is True

    def test_non_stop_event(self):
        entry = {"type": "progress", "data": {"type": "hook_progress", "hookEvent": "PreToolUse"}}
        assert is_session_stop_event(entry) is False

    def test_non_progress_type(self):
        assert is_session_stop_event({"type": "assistant"}) is False


class TestExtractProject:
    """Tests for project path extraction."""

    def test_standard_path(self):
        path = Path("/Users/user/.claude/projects/-Users-user-myproject/session.jsonl")
        name, _ = extract_project_from_path(path)
        assert name == "myproject"


class TestSessionState:
    """Tests for SessionState management."""

    def test_add_thought(self):
        session = SessionState(session_id="t", project="p", project_path="/p", file_path=Path("/tmp/t"))
        session.add_thought(ThinkingBlock(text="thought", timestamp="t", session_id="t"))
        assert len(session.thoughts) == 1
        assert session.status == SessionStatus.ACTIVE

    def test_max_thoughts_limit(self):
        session = SessionState(session_id="t", project="p", project_path="/p", file_path=Path("/tmp/t"))
        for i in range(60):
            session.add_thought(ThinkingBlock(text=f"T{i}", timestamp="t", session_id="t"), max_thoughts=50)
        assert len(session.thoughts) == 50

    def test_get_recent_thoughts(self):
        session = SessionState(session_id="t", project="p", project_path="/p", file_path=Path("/tmp/t"))
        for i in range(10):
            session.add_thought(ThinkingBlock(text=f"T{i}", timestamp="t", session_id="t"))
        assert len(session.get_recent_thoughts(limit=3)) == 3


class TestThinkingBlock:
    """Tests for ThinkingBlock dataclass."""

    def test_default_message_id(self):
        block = ThinkingBlock(text="t", timestamp="t", session_id="s")
        assert block.message_id == ""

    def test_all_fields(self):
        block = ThinkingBlock(text="t", timestamp="ts", session_id="s", message_id="m")
        assert block.message_id == "m"


class TestSessionStatus:
    """Tests for SessionStatus enum."""

    def test_values(self):
        assert SessionStatus.ACTIVE.value == "active"
        assert SessionStatus.IDLE.value == "idle"
        assert SessionStatus.ENDED.value == "ended"
