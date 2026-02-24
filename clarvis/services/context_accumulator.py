"""Context accumulator — stages sessions and items between check-ins."""

import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..core.context_helpers import format_message, iter_transcript_messages
from ..core.persistence import json_load_safe, json_save_atomic

if TYPE_CHECKING:
    from ..core.context import AppContext

logger = logging.getLogger(__name__)

# Bookend preview: first N + last N messages to capture full session arc
_BOOKEND_SIZE = 4
_MAX_MSG_LEN = 400


def extract_project_from_slug(project_slug: str) -> tuple[str, str]:
    """Convert a project slug back to (project_name, project_path).

    The slug is the absolute path with slashes replaced by dashes.
    Ambiguous because directory names can contain dashes. We resolve
    greedily by checking the filesystem, then when the greedy check
    fails we try joining the remaining segments as one hyphenated leaf.

    E.g. "-Users-foo-clarvis-suite" -> ("clarvis-suite", "/Users/foo/clarvis-suite")
    """
    if not project_slug.startswith("-"):
        # Non-absolute slug — can't resolve via filesystem, return as-is
        return project_slug, project_slug

    parts = project_slug[1:].split("-")
    path = "/" + parts[0]

    for i in range(1, len(parts)):
        candidate = path + "/" + parts[i]
        if Path(candidate).is_dir():
            path = candidate
            continue

        # Boundary: remaining segments form the (possibly hyphenated) leaf.
        remaining = "-".join(parts[i:])
        # Try 1: slash + all remaining as one name
        with_slash = path + "/" + remaining
        # Try 2: merge last dir segment with remaining (back up one level)
        parent = str(Path(path).parent)
        merged = parent + "/" + Path(path).name + "-" + remaining

        if Path(merged).is_dir():
            path = merged
        else:
            path = with_slash
        break

    project_name = Path(path).name or project_slug
    return project_name, path


def _extract_preview(transcript_path: str) -> str:
    """Extract a bookend conversation preview from a JSONL transcript.

    Reads the FULL transcript (lazy — only at check-in time) and produces
    a first-N + last-N message preview so the check-in agent can see the
    full arc of the session, not just the tail.
    """
    if not Path(transcript_path).exists():
        return "(transcript not found)"

    raw = iter_transcript_messages(transcript_path)
    if not raw:
        return "(empty session)"

    messages = [format_message(m, max_len=_MAX_MSG_LEN) for m in raw]
    total = len(messages)

    if total <= _BOOKEND_SIZE * 2:
        return "\n".join(messages)

    head = messages[:_BOOKEND_SIZE]
    tail = messages[-_BOOKEND_SIZE:]
    gap = total - _BOOKEND_SIZE * 2
    return "\n".join(head + [f"[... {gap} more messages ...]"] + tail)


class ContextAccumulator:
    """Accumulates session references and staged items between check-ins.

    State is persisted to ``state_dir/state.json`` so it survives
    daemon restarts.

    Two sources of pending content:
    - **Session refs**: Auto-staged from Stop hooks with transcript paths.
      Previews are extracted lazily at check-in time.
    - **Staged items**: Manually added text items.
    """

    def __init__(self, ctx: "AppContext", home_slug: str, state_dir: str = "~/.clarvis/staging"):
        self._state_dir = Path(state_dir).expanduser()
        self._state_file = self._state_dir / "state.json"
        self._last_check_in: datetime = datetime.now(timezone.utc)
        self._staged_items: list[dict[str, Any]] = []
        self._session_refs: list[dict[str, Any]] = []
        self._home_slug = home_slug

        self._lock = threading.Lock()
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._load_state()

        ctx.bus.on("hook:event", self._on_hook_event)

    def _on_hook_event(
        self, signal: str, *, event_name: str = None, session_id: str = "unknown", transcript_path: str = None, **kw
    ) -> None:
        if event_name != "Stop" or not transcript_path:
            return
        slug = Path(transcript_path).parent.name
        if slug == self._home_slug:
            self.stage_session(session_id, transcript_path)

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

    # ------------------------------------------------------------------
    # Check-in bundle
    # ------------------------------------------------------------------

    def get_pending(self) -> dict[str, Any]:
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
            self._save_state(merge=False)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load watermark, staged items, and session refs from state.json."""
        data = json_load_safe(self._state_file)
        if data is None:
            return
        if "last_check_in" in data:
            self._last_check_in = datetime.fromisoformat(data["last_check_in"])
        if "staged_items" in data:
            self._staged_items = data["staged_items"]
        if "session_refs" in data:
            self._session_refs = data["session_refs"]

    def _save_state(self, merge: bool = True) -> None:
        """Read-merge-write: merge any externally-written items before saving.

        Prevents divergence when something else writes to state.json
        (e.g. a script, or a second accumulator instance).
        Pass merge=False when intentionally resetting state (e.g. mark_checked_in).
        """
        try:
            # Merge disk state we don't already have
            if merge:
                disk = json_load_safe(self._state_file) or {}

                # Merge session refs by session_id
                known_ids = {r["session_id"] for r in self._session_refs}
                for ref in disk.get("session_refs", []):
                    if ref.get("session_id") not in known_ids:
                        self._session_refs.append(ref)

                # Merge staged items by (content, timestamp) pair
                known_items = {(it["content"], it["timestamp"]) for it in self._staged_items}
                for item in disk.get("staged_items", []):
                    key = (item.get("content"), item.get("timestamp"))
                    if key not in known_items:
                        self._staged_items.append(item)

            data = {
                "last_check_in": self._last_check_in.isoformat(),
                "staged_items": self._staged_items,
                "session_refs": self._session_refs,
            }
            json_save_atomic(self._state_file, data)
        except OSError as exc:
            logger.debug("Failed to save accumulator state: %s", exc)
