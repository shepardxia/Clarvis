"""Tests for services: location fallback chain."""

from unittest.mock import patch, MagicMock

import pytest

from clarvis.services import location


@pytest.fixture(autouse=True)
def reset_location_cache():
    """Reset module-level cache between tests."""
    location._cache = None
    location._cache_time = 0.0
    location._corelocation_available = None
    yield
    location._cache = None
    location._cache_time = 0.0
    location._corelocation_available = None


class TestGetLocationFull:
    @patch.object(location, "_get_location_corelocation", return_value=None)
    @patch.object(location, "_get_location_ip", return_value=None)
    def test_falls_back_to_default(self, mock_ip, mock_core):
        result = location.get_location_full()
        assert result["city"] == "San Francisco"
        assert result["source"] == "default"

    @patch.object(location, "_get_location_corelocation", return_value=None)
    @patch.object(location, "_get_location_ip", return_value={
        "latitude": 40.7, "longitude": -74.0, "city": "New York",
        "timezone": "America/New_York", "source": "ip",
    })
    def test_ip_fallback(self, mock_ip, mock_core):
        result = location.get_location_full()
        assert result["city"] == "New York"
        assert result["source"] == "ip"

    @patch.object(location, "_get_location_corelocation", return_value={
        "latitude": 37.33, "longitude": -122.03, "city": "Cupertino",
        "timezone": "America/Los_Angeles", "source": "corelocation",
    })
    def test_corelocation_preferred(self, mock_core):
        result = location.get_location_full()
        assert result["city"] == "Cupertino"
        assert result["source"] == "corelocation"

    @patch.object(location, "_get_location_corelocation", return_value=None)
    @patch.object(location, "_get_location_ip", return_value=None)
    def test_cache_used_when_fresh(self, mock_ip, mock_core):
        import time as _time
        location._cache = {
            "latitude": 51.5, "longitude": -0.1, "city": "London",
            "timezone": "Europe/London", "source": "ip",
        }
        location._cache_time = _time.time()

        result = location.get_location_full()
        assert result["city"] == "London"
        # CoreLocation still tried (might have GPS now)
        mock_core.assert_called_once()
        # IP not called since cache was fresh
        mock_ip.assert_not_called()


class TestGetLocation:
    @patch.object(location, "_get_location_corelocation", return_value=None)
    @patch.object(location, "_get_location_ip", return_value=None)
    def test_returns_tuple(self, mock_ip, mock_core):
        lat, lon, city = location.get_location()
        assert lat == pytest.approx(37.7749)
        assert lon == pytest.approx(-122.4194)
        assert city == "San Francisco"


class TestGetCachedTimezone:
    def test_no_cache_returns_none(self):
        assert location.get_cached_timezone() is None

    def test_returns_cached_timezone(self):
        import time as _time
        location._cache = {"timezone": "America/New_York"}
        location._cache_time = _time.time()
        assert location.get_cached_timezone() == "America/New_York"
