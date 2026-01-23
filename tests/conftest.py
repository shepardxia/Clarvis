"""Shared test fixtures."""

import json
import pytest
from pathlib import Path


@pytest.fixture
def temp_hub_files(tmp_path):
    """Create temp file paths for daemon tests."""
    return {
        "status_raw": tmp_path / "claude-status-raw.json",
        "hub_data": tmp_path / "central-hub-data.json",
        "widget_display": tmp_path / "widget-display.json",
        "config": tmp_path / "widget-config.json",
    }


@pytest.fixture
def sample_hook_event():
    """Sample PreToolUse hook event with context_window."""
    return {
        "session_id": "abc-123-def-456",
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "context_window": {
            "used_percentage": 45,
            "total_input_tokens": 45000,
            "context_window_size": 200000,
        },
    }


@pytest.fixture
def sample_hook_events():
    """Multiple hook events for session tracking tests."""
    session_id = "test-session-001"
    return [
        {"session_id": session_id, "hook_event_name": "UserPromptSubmit",
         "context_window": {"used_percentage": 10}},
        {"session_id": session_id, "hook_event_name": "PreToolUse",
         "tool_name": "Read", "context_window": {"used_percentage": 15}},
        {"session_id": session_id, "hook_event_name": "PostToolUse",
         "tool_name": "Read", "context_window": {"used_percentage": 20}},
        {"session_id": session_id, "hook_event_name": "PreToolUse",
         "tool_name": "Bash", "context_window": {"used_percentage": 25}},
        {"session_id": session_id, "hook_event_name": "Stop",
         "context_window": {"used_percentage": 30}},
    ]


@pytest.fixture
def mock_weather_response():
    """Mock Open-Meteo API response."""
    return {
        "current": {
            "temperature_2m": 65.0,
            "weather_code": 3,
            "wind_speed_10m": 12.5,
            "precipitation": 0.0,
            "snowfall": 0.0,
        }
    }


@pytest.fixture
def mock_weather_response_rain():
    """Mock Open-Meteo API response for rainy weather."""
    return {
        "current": {
            "temperature_2m": 55.0,
            "weather_code": 63,  # Rain
            "wind_speed_10m": 25.0,
            "precipitation": 5.5,
            "snowfall": 0.0,
        }
    }


@pytest.fixture
def mock_weather_response_snow():
    """Mock Open-Meteo API response for snowy weather."""
    return {
        "current": {
            "temperature_2m": 28.0,
            "weather_code": 75,  # Heavy Snow
            "wind_speed_10m": 30.0,
            "precipitation": 0.0,
            "snowfall": 3.5,
        }
    }


@pytest.fixture
def sample_jsonl_entry():
    """Sample JSONL entry with thinking block."""
    return {
        "type": "assistant",
        "sessionId": "test-session",
        "timestamp": "2026-01-23T10:00:00Z",
        "uuid": "msg-001",
        "message": {
            "content": [
                {"type": "thinking", "thinking": "Let me analyze this problem..."},
                {"type": "text", "text": "Here's my response."},
            ]
        }
    }


@pytest.fixture
def sample_jsonl_file(tmp_path, sample_jsonl_entry):
    """Create a sample JSONL session file."""
    session_file = tmp_path / "projects" / "test-project" / "test-session.jsonl"
    session_file.parent.mkdir(parents=True)
    session_file.write_text(json.dumps(sample_jsonl_entry) + "\n")
    return session_file
