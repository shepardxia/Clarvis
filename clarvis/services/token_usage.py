"""Token usage tracking service for Claude API."""

import json
import logging
import subprocess
import threading
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class TokenUsageService:
    """Manages token usage fetching and caching."""

    API_URL = "https://api.anthropic.com/api/oauth/usage"
    KEYCHAIN_SERVICE = "Claude Code-credentials"

    def __init__(self, poll_interval: int = 120):
        """Initialize service.

        Args:
            poll_interval: Seconds between API polls (default 120, minimum 10)
        """
        self.poll_interval = max(poll_interval, 10)  # Minimum 10 seconds
        self._token: Optional[str] = None
        self._usage_data: Optional[Dict[str, Any]] = None
        self._last_updated: Optional[datetime] = None
        self._polling_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._retry_delay = 2  # seconds, exponential backoff
        self._max_retry_delay = 30

    def start(self) -> None:
        """Start background polling thread."""
        self._token = self._fetch_from_keychain()
        if not self._token:
            return

        self._stop_event.clear()
        self._polling_thread = threading.Thread(target=self._poll_loop, daemon=True)
        self._polling_thread.start()

    def stop(self) -> None:
        """Stop polling thread gracefully."""
        self._stop_event.set()
        if self._polling_thread:
            self._polling_thread.join(timeout=5)

    def get_usage(self) -> Dict[str, Any]:
        """Return current cached usage data with metadata."""
        with self._lock:
            if not self._usage_data:
                return {"error": "Usage data not available", "is_stale": True}

            staleness = (
                (datetime.now(timezone.utc) - self._last_updated).total_seconds() if self._last_updated else None
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
            )

            if result.returncode != 0:
                logger.debug("Keychain access failed: %s", result.stderr.decode().strip())
                return None

            # Parse JSON response
            data = json.loads(result.stdout.decode())
            return data.get("claudeAiOauth", {}).get("accessToken")
        except Exception as e:
            logger.debug("Failed to get token from keychain: %s", e)
            return None

    def _poll_loop(self) -> None:
        """Background thread that polls API periodically with retry logic."""
        retry_delay = self._retry_delay

        while not self._stop_event.is_set():
            usage = self._fetch_usage()

            if usage:
                with self._lock:
                    self._usage_data = usage
                    self._last_updated = datetime.now(timezone.utc)
                retry_delay = self._retry_delay  # reset on success
                wait_time = self.poll_interval
            else:
                # Exponential backoff on failure
                wait_time = retry_delay
                retry_delay = min(retry_delay * 2, self._max_retry_delay)

            # Sleep until next poll or stop event
            self._stop_event.wait(wait_time)

    def _fetch_usage(self) -> Optional[Dict[str, Any]]:
        """Make single API request to get token usage.

        Returns:
            Parsed usage data or None on failure
        """
        if not self._token:
            return None

        try:
            import requests

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
            logger.debug("Failed to fetch token usage: %s", e)
            return None
