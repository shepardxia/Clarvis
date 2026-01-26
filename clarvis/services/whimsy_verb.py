"""Generate whimsical verbs describing Claude's activity using DSPy."""

from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import dspy

# Load .env
_env = Path(__file__).parent.parent.parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SYSTEM_PROMPT = """Analyze this message and come up with a single positive, cheerful and delightful verb in gerund form that's related to the message. Only include the word with no other text or punctuation. The word should have the first letter capitalized. Add some whimsy and surprise to entertain the user. Ensure the word is highly relevant to the user's message. Synonyms are welcome, including obscure words. Be careful to avoid words that might look alarming or concerning to the software engineer seeing it as a status notification, such as Connecting, Disconnecting, Retrying, Lagging, Freezing, etc. NEVER use a destructive word, such as Terminating, Killing, Deleting, Destroying, Stopping, Exiting, or similar. NEVER use a word that may be derogatory, offensive, or inappropriate in a non-coding context, such as Penetrating."""


def generate_whimsy_verb(context: str) -> str:
    """Generate a whimsical gerund verb for the given context."""
    lm = dspy.LM(
        model="anthropic/claude-haiku-4-5",
        api_key=os.environ.get("ANTHROPIC_API_KEY"),
        max_tokens=20,
        temperature=0.9,
    )

    response = lm(messages=[
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": context[:2000]},  # Truncate
    ])

    return response[0].strip().split()[0].title()


class WhimsyManager:
    """Manages whimsy verb generation with cooldown, stats, and thread safety."""

    # Configuration
    DEFAULT_COOLDOWN = 5.0  # seconds between generations
    COST_PER_CALL = 0.00065  # ~614 input + ~5 output tokens on Haiku

    def __init__(
        self,
        stats_file: Path = None,
        cooldown: float = DEFAULT_COOLDOWN,
        context_provider: Callable[[], str] = None,
    ):
        self._stats_file = stats_file or Path("/tmp/clarvis-whimsy-stats.json")
        self._cooldown = cooldown
        self._context_provider = context_provider

        self._lock = threading.Lock()
        self._last_time: float = 0
        self._current_verb: Optional[str] = None
        self._call_count, self._total_cost = self._load_stats()

    @property
    def current_verb(self) -> Optional[str]:
        """Get current whimsy verb (thread-safe)."""
        with self._lock:
            return self._current_verb

    @property
    def stats(self) -> dict:
        """Get usage statistics."""
        with self._lock:
            return {
                "current_verb": self._current_verb,
                "call_count": self._call_count,
                "total_cost": round(self._total_cost, 6),
                "cost_per_call": self.COST_PER_CALL,
                "cooldown_seconds": self._cooldown,
            }

    def clear(self) -> None:
        """Clear current verb (e.g., when session ends)."""
        with self._lock:
            self._current_verb = None

    def maybe_generate(self, event: str) -> bool:
        """Trigger generation if appropriate for the event.

        Args:
            event: Hook event name (UserPromptSubmit, Stop, etc.)

        Returns:
            True if generation was triggered
        """
        # Clear verb on session end
        if event in ("Stop", "Notification"):
            self.clear()
            return False

        # Only generate on user prompt
        if event != "UserPromptSubmit":
            return False

        # Check cooldown
        now = time.time()
        with self._lock:
            if now - self._last_time < self._cooldown:
                return False
            self._last_time = now

        # Generate in background
        thread = threading.Thread(target=self._generate, daemon=True)
        thread.start()
        return True

    def generate_sync(self, context: str) -> dict:
        """Generate verb synchronously (for MCP tool calls).

        Args:
            context: Text context to generate verb from

        Returns:
            Dict with verb and metadata
        """
        if not context:
            return {"verb": None, "error": "No context provided"}

        try:
            verb = generate_whimsy_verb(context)
            with self._lock:
                self._call_count += 1
                self._total_cost += self.COST_PER_CALL
            self._save_stats()
            return {"verb": verb, "context_length": len(context)}
        except Exception as e:
            return {"verb": None, "error": str(e)}

    def _generate(self) -> None:
        """Generate verb from context provider (background thread)."""
        if not self._context_provider:
            return

        try:
            context = self._context_provider()
            if not context:
                return

            verb = generate_whimsy_verb(context)

            with self._lock:
                self._current_verb = verb
                self._call_count += 1
                self._total_cost += self.COST_PER_CALL

            self._save_stats()

        except Exception as e:
            print(f"Whimsy generation error: {e}")

    def _load_stats(self) -> tuple[int, float]:
        """Load stats from file."""
        try:
            if self._stats_file.exists():
                data = json.loads(self._stats_file.read_text())
                return data.get("call_count", 0), data.get("total_cost", 0.0)
        except Exception:
            pass
        return 0, 0.0

    def _save_stats(self) -> None:
        """Save stats to file."""
        try:
            with self._lock:
                data = {
                    "call_count": self._call_count,
                    "total_cost": self._total_cost,
                }
            self._stats_file.write_text(json.dumps(data))
        except Exception:
            pass


if __name__ == "__main__":
    context = "Debugging a null pointer exception in the auth module"
    for i in range(5):
        print(generate_whimsy_verb(context))
