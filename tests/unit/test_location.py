"""Tests for location service."""

import pytest
import responses

from central_hub.services.location import get_cached_timezone


class TestGetCachedTimezone:
    """Tests for timezone caching."""

    @responses.activate
    def test_get_timezone_from_api(self):
        """Test timezone lookup via API."""
        responses.add(
            responses.GET,
            "http://ip-api.com/json/",
            json={
                "status": "success",
                "lat": 37.7749,
                "lon": -122.4194,
                "city": "San Francisco",
                "timezone": "America/Los_Angeles",
            },
            status=200,
        )

        timezone = get_cached_timezone()
        # Should return a timezone string
        assert timezone is not None
        assert "/" in timezone or timezone in ["UTC", "GMT"]

    @responses.activate
    def test_get_timezone_api_failure_returns_default(self):
        """Should return default timezone on API failure."""
        responses.add(
            responses.GET,
            "http://ip-api.com/json/",
            status=500,
        )

        # Should not raise, returns default
        timezone = get_cached_timezone()
        assert timezone is not None
