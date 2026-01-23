"""Tests for location service."""

import pytest
import responses
from unittest.mock import patch

from central_hub.services.location import (
    get_location,
    get_cached_timezone,
    DEFAULT_LOCATION,
)


class TestGetLocation:
    """Tests for location retrieval."""

    @responses.activate
    @patch("central_hub.services.location._is_corelocation_available", return_value=False)
    def test_get_location_from_ip_api(self, mock_coreloc):
        """Test location lookup via IP API."""
        responses.add(
            responses.GET,
            "http://ip-api.com/json/",
            json={
                "status": "success",
                "lat": 37.7749,
                "lon": -122.4194,
                "city": "San Francisco",
                "regionName": "California",
                "country": "USA",
                "timezone": "America/Los_Angeles",
            },
            status=200,
        )

        # Clear cache by mocking get_hub_section to return None
        with patch("central_hub.services.location.get_hub_section", return_value=None):
            with patch("central_hub.services.location.write_hub_section"):
                lat, lon, city = get_location()

        assert lat == 37.7749
        assert lon == -122.4194
        assert city == "San Francisco"

    @responses.activate
    @patch("central_hub.services.location._is_corelocation_available", return_value=False)
    def test_get_location_api_failure_returns_default(self, mock_coreloc):
        """Should return default location on API failure."""
        responses.add(
            responses.GET,
            "http://ip-api.com/json/",
            status=500,
        )

        with patch("central_hub.services.location.get_hub_section", return_value=None):
            lat, lon, city = get_location()

        assert (lat, lon, city) == DEFAULT_LOCATION


class TestGetCachedTimezone:
    """Tests for timezone caching."""

    def test_get_timezone_from_cache(self):
        """Test timezone retrieval from cache."""
        cached_data = {
            "latitude": 37.7749,
            "longitude": -122.4194,
            "city": "San Francisco",
            "timezone": "America/Los_Angeles",
        }

        with patch("central_hub.services.location.get_hub_section", return_value=cached_data):
            timezone = get_cached_timezone()

        assert timezone == "America/Los_Angeles"

    def test_get_timezone_no_cache(self):
        """Should return None when cache is empty."""
        with patch("central_hub.services.location.get_hub_section", return_value=None):
            timezone = get_cached_timezone()

        assert timezone is None
