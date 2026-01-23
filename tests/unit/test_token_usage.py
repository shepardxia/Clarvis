"""Tests for token usage service."""

import pytest
import json
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from central_hub.services.token_usage import TokenUsageService


class TestTokenUsageService:
    """Tests for TokenUsageService."""

    def test_initialization(self):
        """Should initialize with default poll interval."""
        service = TokenUsageService()
        assert service.poll_interval == 120
        assert service._token is None
        assert service._usage_data is None

    def test_custom_poll_interval(self):
        """Should accept custom poll interval."""
        service = TokenUsageService(poll_interval=60)
        assert service.poll_interval == 60

    @patch("central_hub.services.token_usage.subprocess.run")
    def test_fetch_from_keychain_success(self, mock_run):
        """Should retrieve OAuth token from Keychain."""
        mock_run.return_value.stdout = b'{"claudeAiOauth":{"accessToken":"test-token-123"}}'
        
        service = TokenUsageService()
        token = service._fetch_from_keychain()
        
        assert token == "test-token-123"
        mock_run.assert_called_once()

    @patch("central_hub.services.token_usage.subprocess.run")
    def test_fetch_from_keychain_failure(self, mock_run):
        """Should return None if Keychain access fails."""
        mock_run.side_effect = Exception("Keychain error")
        
        service = TokenUsageService()
        token = service._fetch_from_keychain()
        
        assert token is None

    @patch("central_hub.services.token_usage.requests.get")
    def test_fetch_usage_success(self, mock_get):
        """Should fetch and cache usage data from API."""
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "five_hour": {"utilization": 6.0, "resets_at": "2025-11-04T04:59:59Z"},
            "seven_day": {"utilization": 35.0, "resets_at": "2025-11-06T03:59:59Z"},
        }
        mock_get.return_value = mock_response
        
        service = TokenUsageService()
        service._token = "test-token"
        result = service._fetch_usage()
        
        assert result is not None
        assert "five_hour" in result
        assert "seven_day" in result

    @patch("central_hub.services.token_usage.requests.get")
    def test_fetch_usage_failure(self, mock_get):
        """Should return None on API failure."""
        mock_get.side_effect = Exception("Network error")
        
        service = TokenUsageService()
        service._token = "test-token"
        result = service._fetch_usage()
        
        assert result is None

    def test_get_usage_returns_cached_data(self):
        """Should return cached usage data with metadata."""
        service = TokenUsageService()
        service._usage_data = {
            "five_hour": {"utilization": 6.0, "resets_at": "2025-11-04T04:59:59Z"},
            "seven_day": {"utilization": 35.0, "resets_at": "2025-11-06T03:59:59Z"},
        }
        
        result = service.get_usage()
        
        assert "five_hour" in result
        assert "seven_day" in result
        assert "last_updated" in result
        assert "is_stale" in result

    def test_get_usage_when_no_data(self):
        """Should return error state when no data fetched yet."""
        service = TokenUsageService()
        result = service.get_usage()

        assert "error" in result or result.get("is_stale") is True

    def test_staleness_calculation_exact_threshold(self):
        """Should mark as stale when exactly 2x poll interval has passed."""
        service = TokenUsageService(poll_interval=10)
        service._usage_data = {"five_hour": {"utilization": 5.0}}
        service._last_updated = datetime.now(timezone.utc) - timedelta(seconds=21)

        result = service.get_usage()

        # Should be marked stale (21 seconds > 20 second threshold)
        assert result.get("is_stale") is True

    def test_staleness_calculation_not_yet_stale(self):
        """Should not mark as stale when under 2x poll interval."""
        service = TokenUsageService(poll_interval=10)
        service._usage_data = {"five_hour": {"utilization": 5.0}}
        service._last_updated = datetime.now(timezone.utc) - timedelta(seconds=19)

        result = service.get_usage()

        # Should not be marked stale (19 seconds < 20 second threshold)
        assert result.get("is_stale") is False

    @patch("central_hub.services.token_usage.TokenUsageService._fetch_usage")
    @patch("central_hub.services.token_usage.TokenUsageService._fetch_from_keychain")
    def test_stop_waits_for_thread_completion(self, mock_keychain, mock_fetch):
        """Should wait for polling thread to complete on stop."""
        mock_keychain.return_value = "test-token"
        mock_fetch.return_value = {"five_hour": {"utilization": 5.0}, "seven_day": {"utilization": 20.0}}

        service = TokenUsageService(poll_interval=1)
        service.start()

        time.sleep(0.1)  # Let thread start
        service.stop()

        # Thread should have been joined
        assert service._polling_thread is None or not service._polling_thread.is_alive()
