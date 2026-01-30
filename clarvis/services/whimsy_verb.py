"""Generate whimsical verbs describing Claude's activity."""

from __future__ import annotations

import json
import os
import random
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from litellm import completion

# Load .env
_env = Path(__file__).parent.parent.parent / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SYSTEM_PROMPT = """Generate ONE whimsical gerund (-ing word) that captures what the assistant is doing. Match the task, mood, and environment. Prefer obscure/delightful words. NEVER use: Terminating, Killing, Deleting, Dying, Crashing.{avoid}
Output ONLY the word."""

# Track recent verbs to avoid repetition
_verb_history: list[str] = []
_history_lock = threading.Lock()
HISTORY_SIZE = 10


def _add_to_history(verb: str) -> None:
    """Add verb to history, maintaining max size."""
    with _history_lock:
        _verb_history.append(verb)
        if len(_verb_history) > HISTORY_SIZE:
            _verb_history.pop(0)


def _get_avoid_list() -> str:
    """Get recent verbs to avoid."""
    with _history_lock:
        if _verb_history:
            return f"\nAvoid: {', '.join(_verb_history[-5:])}"
        return ""


def generate_whimsy_verb(context: str) -> str:
    """Generate a whimsical gerund verb matching what Claude is doing.

    Uses ~150-200 tokens, costs ~$0.00015 per call on Haiku 3.5.
    """
    avoid = _get_avoid_list()
    prompt = SYSTEM_PROMPT.format(avoid=avoid)

    response = completion(
        model="anthropic/claude-3-5-haiku-20241022",
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": context[:1500]},  # More room for rich context
        ],
        max_tokens=10,
        temperature=0.9,
    )

    verb = response.choices[0].message.content.strip()
    verb = verb.split()[0].rstrip(".,!?:;").title()

    _add_to_history(verb)
    return verb


class WhimsyManager:
    """Manages whimsy verb generation with cooldown, stats, and thread safety."""

    # Configuration
    DEFAULT_COOLDOWN = 5.0  # seconds between generations
    COST_PER_CALL = 0.0002  # ~180 input + 6 output tokens on Haiku 3.5
    ALERT_THRESHOLD = 5.0  # Alert every $5 spent

    def __init__(
        self,
        stats_file: Path = None,
        cooldown: float = DEFAULT_COOLDOWN,
        context_provider: Callable[[], str] = None,
        on_cost_alert: Callable[[float, int], None] = None,
    ):
        self._stats_file = stats_file or Path("/tmp/clarvis-whimsy-stats.json")
        self._cooldown = cooldown
        self._context_provider = context_provider
        self._on_cost_alert = on_cost_alert  # callback(total_cost, call_count)

        self._lock = threading.Lock()
        self._last_time: float = 0
        self._current_verb: Optional[str] = None
        self._call_count, self._total_cost, self._last_alerted = self._load_stats()

    @property
    def current_verb(self) -> Optional[str]:
        """Get current whimsy verb (thread-safe)."""
        with self._lock:
            return self._current_verb

    @property
    def stats(self) -> dict:
        """Get usage statistics."""
        with self._lock:
            next_alert = ((self._total_cost // self.ALERT_THRESHOLD) + 1) * self.ALERT_THRESHOLD
            return {
                "current_verb": self._current_verb,
                "call_count": self._call_count,
                "total_cost": round(self._total_cost, 6),
                "cost_per_call": self.COST_PER_CALL,
                "cooldown_seconds": self._cooldown,
                "next_alert_at": next_alert,
                "calls_until_alert": int((next_alert - self._total_cost) / self.COST_PER_CALL),
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
            self._check_cost_alert()
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
            self._check_cost_alert()

        except Exception as e:
            print(f"Whimsy generation error: {e}")

    def _load_stats(self) -> tuple[int, float, float]:
        """Load stats from file."""
        try:
            if self._stats_file.exists():
                data = json.loads(self._stats_file.read_text())
                return (
                    data.get("call_count", 0),
                    data.get("total_cost", 0.0),
                    data.get("last_alerted", 0.0),
                )
        except Exception:
            pass
        return 0, 0.0, 0.0

    def _save_stats(self) -> None:
        """Save stats to file."""
        try:
            with self._lock:
                data = {
                    "call_count": self._call_count,
                    "total_cost": self._total_cost,
                    "last_alerted": self._last_alerted,
                }
            self._stats_file.write_text(json.dumps(data))
        except Exception:
            pass

    def _check_cost_alert(self) -> None:
        """Check if we've crossed a cost threshold and alert."""
        should_alert = False
        cost = 0.0
        count = 0
        next_threshold = 0.0

        with self._lock:
            # Calculate which $5 threshold we're at
            current_threshold = (self._total_cost // self.ALERT_THRESHOLD) * self.ALERT_THRESHOLD

            # If we've crossed a new threshold
            if current_threshold > self._last_alerted and current_threshold > 0:
                self._last_alerted = current_threshold
                should_alert = True
                cost = self._total_cost
                count = self._call_count
                next_threshold = current_threshold + self.ALERT_THRESHOLD

        # Alert outside the lock
        if should_alert:
            msg = f"[Whimsy Cost Alert] ${cost:.2f} spent ({count:,} calls). Next alert at ${next_threshold:.0f}."
            print(msg)

            # Call custom handler if provided
            if self._on_cost_alert:
                try:
                    self._on_cost_alert(cost, count)
                except Exception:
                    pass


if __name__ == "__main__":
    context = "Debugging a null pointer exception in the auth module"
    for i in range(5):
        print(generate_whimsy_verb(context))
