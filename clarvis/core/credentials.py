"""Shared macOS Keychain credential retrieval for Claude OAuth tokens."""

import json
import logging
import subprocess

logger = logging.getLogger(__name__)

KEYCHAIN_SERVICE = "Claude Code-credentials"


def get_oauth_token() -> str | None:
    """Retrieve Claude OAuth access token from macOS Keychain.

    Returns:
        OAuth access token or None if retrieval fails.
    """
    try:
        result = subprocess.run(
            [
                "security",
                "find-generic-password",
                "-s",
                KEYCHAIN_SERVICE,
                "-w",
            ],
            capture_output=True,
            text=False,
            timeout=5,
        )

        if result.returncode != 0:
            logger.debug("Keychain access failed: %s", result.stderr.decode().strip())
            return None

        data = json.loads(result.stdout.decode())
        return data.get("claudeAiOauth", {}).get("accessToken")
    except subprocess.TimeoutExpired:
        logger.warning("Keychain access timed out after 5s")
        return None
    except Exception as e:
        logger.debug("Failed to get token from keychain: %s", e)
        return None
