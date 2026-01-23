"""Tests for file-based caching utilities."""

import json
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from central_hub.core.cache import (
    read_hub_data,
    write_hub_section,
    get_hub_section,
    HUB_DATA_FILE,
    DEFAULT_CACHE_DURATION,
)


@pytest.fixture
def temp_hub_file(tmp_path):
    """Use a temporary file for hub data."""
    test_file = tmp_path / "test-hub-data.json"
    with patch("central_hub.core.cache.HUB_DATA_FILE", test_file):
        yield test_file


class TestReadHubData:
    """Tests for read_hub_data function."""

    def test_returns_empty_dict_when_file_missing(self, temp_hub_file):
        """Should return empty dict when file doesn't exist."""
        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            result = read_hub_data()
        assert result == {}

    def test_reads_existing_data(self, temp_hub_file):
        """Should read existing JSON data."""
        test_data = {"weather": {"temp": 72}, "time": {"tz": "PST"}}
        temp_hub_file.write_text(json.dumps(test_data))

        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            result = read_hub_data()

        assert result == test_data

    def test_handles_invalid_json(self, temp_hub_file):
        """Should return empty dict for invalid JSON."""
        temp_hub_file.write_text("not valid json {{{")

        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            result = read_hub_data()

        assert result == {}


class TestWriteHubSection:
    """Tests for write_hub_section function."""

    def test_writes_new_section(self, temp_hub_file):
        """Should write a new section to empty file."""
        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            write_hub_section("weather", {"temp": 72, "humidity": 50})

        data = json.loads(temp_hub_file.read_text())
        assert "weather" in data
        assert data["weather"]["temp"] == 72
        assert data["weather"]["humidity"] == 50
        assert "updated_at" in data["weather"]
        assert "last_updated" in data

    def test_updates_existing_section(self, temp_hub_file):
        """Should update existing section."""
        initial = {"weather": {"temp": 65, "updated_at": "2024-01-01T00:00:00"}}
        temp_hub_file.write_text(json.dumps(initial))

        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            write_hub_section("weather", {"temp": 72})

        data = json.loads(temp_hub_file.read_text())
        assert data["weather"]["temp"] == 72

    def test_preserves_other_sections(self, temp_hub_file):
        """Should not affect other sections."""
        initial = {"time": {"tz": "PST", "updated_at": "2024-01-01T00:00:00"}}
        temp_hub_file.write_text(json.dumps(initial))

        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            write_hub_section("weather", {"temp": 72})

        data = json.loads(temp_hub_file.read_text())
        assert data["time"]["tz"] == "PST"
        assert "weather" in data

    def test_adds_timestamp(self, temp_hub_file):
        """Should add updated_at timestamp."""
        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            write_hub_section("test", {"value": 1})

        data = json.loads(temp_hub_file.read_text())
        # Verify timestamp is valid ISO format
        datetime.fromisoformat(data["test"]["updated_at"])
        datetime.fromisoformat(data["last_updated"])


class TestGetHubSection:
    """Tests for get_hub_section function."""

    def test_returns_none_for_missing_section(self, temp_hub_file):
        """Should return None when section doesn't exist."""
        temp_hub_file.write_text(json.dumps({}))

        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            result = get_hub_section("nonexistent")

        assert result is None

    def test_returns_fresh_data(self, temp_hub_file):
        """Should return data when fresh."""
        now = datetime.now().isoformat()
        data = {"weather": {"temp": 72, "updated_at": now}}
        temp_hub_file.write_text(json.dumps(data))

        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            result = get_hub_section("weather", max_age=60)

        assert result is not None
        assert result["temp"] == 72

    def test_returns_none_for_stale_data(self, temp_hub_file):
        """Should return None when data is too old."""
        old_time = (datetime.now() - timedelta(seconds=120)).isoformat()
        data = {"weather": {"temp": 72, "updated_at": old_time}}
        temp_hub_file.write_text(json.dumps(data))

        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            result = get_hub_section("weather", max_age=60)

        assert result is None

    def test_returns_none_for_missing_timestamp(self, temp_hub_file):
        """Should return None when updated_at is missing."""
        data = {"weather": {"temp": 72}}  # No updated_at
        temp_hub_file.write_text(json.dumps(data))

        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            result = get_hub_section("weather")

        assert result is None

    def test_returns_none_for_invalid_timestamp(self, temp_hub_file):
        """Should return None when updated_at is invalid."""
        data = {"weather": {"temp": 72, "updated_at": "not-a-timestamp"}}
        temp_hub_file.write_text(json.dumps(data))

        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            result = get_hub_section("weather")

        assert result is None

    def test_custom_max_age(self, temp_hub_file):
        """Should respect custom max_age parameter."""
        # Data 90 seconds old
        old_time = (datetime.now() - timedelta(seconds=90)).isoformat()
        data = {"weather": {"temp": 72, "updated_at": old_time}}
        temp_hub_file.write_text(json.dumps(data))

        with patch("central_hub.core.cache.HUB_DATA_FILE", temp_hub_file):
            # Should be stale with 60s max_age
            assert get_hub_section("weather", max_age=60) is None
            # Should be fresh with 120s max_age
            assert get_hub_section("weather", max_age=120) is not None
