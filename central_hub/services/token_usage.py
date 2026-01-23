"""Token usage tracking service for Claude API."""

import subprocess
import json
import requests
import threading
import time
from datetime import datetime
from typing import Optional, Dict, Any


class TokenUsageService:
    """Manages token usage fetching and caching."""

    API_URL = "https://api.anthropic.com/api/oauth/usage"
    KEYCHAIN_SERVICE = "Claude Code-credentials"

    def __init__(self, poll_interval: int = 120):
        """Initialize service.

        Args:
            poll_interval: Seconds between API polls (default 120)
        """
        self.poll_interval = poll_interval
        self._token: Optional[str] = None
        self._usage_data: Optional[Dict[str, Any]] = None
        self._last_updated: Optional[datetime] = None
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._retry_delay = 2  # seconds, exponential backoff
        self._max_retry_delay = 30

    def start(self) -> None:
        """Start background polling thread."""
        self._token = self._fetch_from_keychain()
        if not self._token:
            return

        self._stop_event.clear()
        self._polling_thread = threading.Thread(
            target=self._poll_loop, daemon=True
        )
        self._polling_thread.start()

    def stop(self) -> None:
        """Stop polling thread gracefully."""
        self._stop_event.set()
        if self._polling_thread:
            self._polling_thread.join(timeout=5)

    def get_usage(self) -> Dict[str, Any]:
        """Return current cached usage data with metadata."""
        if not self._usage_data:
            return {"error": "Usage data not available", "is_stale": True}

        staleness = (
            (datetime.utcnow() - self._last_updated).total_seconds()
            if self._last_updated
            else None
        )

        return {
            **self._usage_data,
            "last_updated": self._last_updated.isoformat() if self._last_updated else None,
            "is_stale": staleness and staleness > self.poll_interval * 2,
        }

    def _fetch_from_keychain(self) -> Optional[str]:
        """Retrieve OAuth token from macOS Keychain.

        Returns:
            OAuth access token or None if retrieval fails
        """
        try:
            result = subprocess.run(
                [
                    "security",
                    "find-generic-password",
                    "-s",
                    self.KEYCHAIN_SERVICE,
                    "-w",
                ],
                capture_output=True,
                text=False,
                check=True,
            )

            # Parse JSON response
            data = json.loads(result.stdout.decode())
            return data.get("claudeAiOauth", {}).get("accessToken")
        except Exception as e:
            return None

    def _poll_loop(self) -> None:
        """Background thread that polls API periodically with retry logic."""
        retry_delay = self._retry_delay

        while not self._stop_event.is_set():
            usage = self._fetch_usage()

            if usage:
                self._usage_data = usage
                self._last_updated = datetime.utcnow()
                retry_delay = self._retry_delay  # reset on success
            else:
                # Exponential backoff on failure
                retry_delay = min(retry_delay * 2, self._max_retry_delay)

            # Sleep until next poll or stop event
            self._stop_event.wait(self.poll_interval)

    def _fetch_usage(self) -> Optional[Dict[str, Any]]:
        """Make single API request to get token usage.

        Returns:
            Parsed usage data or None on failure
        """
        if not self._token:
            return None

        try:
            response = requests.get(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "Content-Type": "application/json",
                    "User-Agent": "claude-code/2.0.31",
                    "anthropic-beta": "oauth-2025-04-20",
                },
                timeout=5,
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            return None
