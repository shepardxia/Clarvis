"""Context accumulator for memory check-in flow.

Tracks completed sessions and manually staged items between check-ins.
Sessions are staged automatically at Stop time via the daemon hook pipeline.
Staged items come from /remember or other manual triggers.

The check_in MCP tool reads get_pending() to present a context bundle.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Max user/assistant messages to extract as a session preview
_PREVIEW_MESSAGES = 8
_MAX_MSG_LEN = 300


def extract_project_from_slug(project_slug: str) -> tuple[str, str]:
    """Convert a project slug back to (project_name, project_path).

    The slug is the absolute path with slashes replaced by dashes.
    E.g. "-Users-foo-my-project" -> ("my-project", "/Users/foo/my/project")
    """
    if project_slug.startswith("-"):
        project_path = "/" + project_slug[1:].replace("-", "/")
    else:
        project_path = project_slug.replace("-", "/")

    project_name = Path(project_path).name or project_slug
    return project_name, project_path


def _extract_preview(transcript_path: str) -> str:
    """Extract a compact conversation preview from a JSONL transcript.

    Reads the last N user/assistant messages, skipping system tags and
    tool_use blocks. Returns a compact string suitable for check-in review.
    """
    tp = Path(transcript_path)
    if not tp.exists():
        return "(transcript not found)"

    try:
        from collections import deque

        tail: deque[str] = deque(maxlen=100)
        with open(tp, encoding="utf-8", errors="replace") as f:
            for line in f:
                tail.append(line.rstrip("\n"))
        lines = list(tail)
    except OSError:
        return "(unable to read transcript)"

    messages: List[str] = []
    # Walk backwards through recent lines
    for line in reversed(lines[-100:]):
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        entry_type = entry.get("type")
        if entry_type not in ("user", "assistant"):
            continue

        content = entry.get("message", {}).get("content", "")

        # Flatten content arrays (skip tool_use, system reminders)
        if isinstance(content, list):
            texts = [
                c.get("text", "")
                for c in content
                if c.get("type") == "text" and not c.get("text", "").startswith("<system")
            ]
            content = " ".join(texts)

        if not content or content.startswith("<system"):
            continue

        role = "U" if entry_type == "user" else "A"
        content = content[:_MAX_MSG_LEN].replace("\n", " ").strip()
        messages.append(f"{role}: {content}")

        if len(messages) >= _PREVIEW_MESSAGES:
            break

    if not messages:
        return "(empty session)"

    messages.reverse()
    return "\n".join(messages)


class ContextAccumulator:
    """Accumulates session references and staged items between check-ins.

    State is persisted to ``state_dir/state.json`` so it survives
    daemon restarts.

    Two sources of pending content:
    - **Session refs**: Auto-staged from Stop hooks with transcript paths.
      Previews are extracted lazily at check-in time.
    - **Staged items**: Manually added via stage_item() (from /remember etc).
    """

    def __init__(self, state_dir: str = "~/.clarvis/staging"):
        self._state_dir = Path(state_dir).expanduser()
        self._state_file = self._state_dir / "state.json"
        self._last_check_in: datetime = datetime.now(timezone.utc)
        self._staged_items: List[Dict[str, Any]] = []
        self._session_refs: List[Dict[str, Any]] = []

        self._lock = threading.Lock()
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()

    # ------------------------------------------------------------------
    # Staging (called by daemon on Stop events)
    # ------------------------------------------------------------------

    def stage_session(self, session_id: str, transcript_path: str) -> None:
        """Stage a completed session for check-in review.

        Called by the daemon when a Stop hook event fires. Derives project
        info from the transcript path and stores a reference. The actual
        transcript content is read lazily at check-in time.
        """
        with self._lock:
            # Dedup
            if session_id in {ref["session_id"] for ref in self._session_refs}:
                return

            tp = Path(transcript_path)
            project_slug = tp.parent.name
            project_name, project_path = extract_project_from_slug(project_slug)

            self._session_refs.append(
                {
                    "session_id": session_id,
                    "project_name": project_name,
                    "project_path": project_path,
                    "transcript_path": transcript_path,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._save_state()
            logger.debug("Staged session %s (%s)", session_id[:8], project_name)

    def stage_item(self, content: str) -> None:
        """Add a manually staged item to the pending list."""
        with self._lock:
            self._staged_items.append(
                {
                    "content": content,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )
            self._save_state()

    # ------------------------------------------------------------------
    # Check-in bundle
    # ------------------------------------------------------------------

    def get_pending(self) -> Dict[str, Any]:
        """Return accumulated context for the check_in tool.

        Session previews are extracted lazily from transcripts.
        """
        with self._lock:
            refs = list(self._session_refs)
            items = list(self._staged_items)
            check_in_ts = self._last_check_in.isoformat()

        # Preview extraction happens outside the lock (I/O-heavy)
        sessions = []
        for ref in refs:
            sessions.append(
                {
                    "session_id": ref["session_id"],
                    "project": ref["project_name"],
                    "project_path": ref["project_path"],
                    "timestamp": ref.get("timestamp"),
                    "preview": _extract_preview(ref["transcript_path"]),
                }
            )

        return {
            "sessions_since_last": sessions,
            "staged_items": items,
            "last_check_in": check_in_ts,
        }

    def mark_checked_in(self) -> None:
        """Advance the watermark to now and clear accumulated items."""
        with self._lock:
            self._last_check_in = datetime.now(timezone.utc)
            self._staged_items.clear()
            self._session_refs.clear()
            self._save_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load watermark, staged items, and session refs from state.json."""
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            if "last_check_in" in data:
                self._last_check_in = datetime.fromisoformat(data["last_check_in"])
            if "staged_items" in data:
                self._staged_items = data["staged_items"]
            if "session_refs" in data:
                self._session_refs = data["session_refs"]
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.debug("Failed to load accumulator state: %s", exc)

    def _save_state(self) -> None:
        """Persist watermark, staged items, and session refs to state.json."""
        try:
            data = {
                "last_check_in": self._last_check_in.isoformat(),
                "staged_items": self._staged_items,
                "session_refs": self._session_refs,
            }
            self._state_file.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.debug("Failed to save accumulator state: %s", exc)
