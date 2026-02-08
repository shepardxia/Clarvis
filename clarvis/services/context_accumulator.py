"""Context accumulator for memory check-in flow.

Tracks sessions completed since the last check-in using a watermark timestamp.
Discovers session summaries under ~/.claude/projects/ and accumulates manually
staged items. The check_in MCP tool reads this to present a context bundle.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Claude Code session files live here
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"


def extract_project_from_slug(project_slug: str) -> tuple[str, str]:
    """Convert a project slug back to (project_name, project_path).

    Session dirs are at: ~/.claude/projects/{project-slug}/{session-id}/
    The slug is the absolute path with slashes replaced by dashes.
    """
    if project_slug.startswith("-"):
        project_path = "/" + project_slug[1:].replace("-", "/")
    else:
        project_path = project_slug.replace("-", "/")

    project_name = Path(project_path).name or project_slug
    return project_name, project_path


class ContextAccumulator:
    """Accumulates session references and staged items between check-ins.

    State is persisted to ``state_dir/state.json`` so the watermark survives
    daemon restarts.

    Attributes:
        _last_check_in: Watermark — sessions newer than this are "pending".
        _staged_items: Manually added items (via stage_item).
        _session_refs: Discovered session references (populated by accumulate).
    """

    def __init__(self, state_dir: str = "~/.clarvis/staging"):
        self._state_dir = Path(state_dir).expanduser()
        self._state_file = self._state_dir / "state.json"
        self._last_check_in: datetime = datetime.now(timezone.utc)
        self._staged_items: List[Dict[str, Any]] = []
        self._session_refs: List[Dict[str, Any]] = []

        # Ensure state directory exists
        self._state_dir.mkdir(parents=True, exist_ok=True)

        # Load persisted state if available
        self._load_state()

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def accumulate(self) -> None:
        """Scan for sessions completed after the watermark.

        Walks ~/.claude/projects/{project-slug}/{session-id}/session-memory/
        looking for summary.md files newer than _last_check_in.
        Stores references only (lazy loading on get_pending).
        """
        if not CLAUDE_PROJECTS_DIR.exists():
            return

        watermark_ts = self._last_check_in.timestamp()
        found_ids = {ref["session_id"] for ref in self._session_refs}

        try:
            for project_dir in CLAUDE_PROJECTS_DIR.iterdir():
                if not project_dir.is_dir():
                    continue

                project_slug = project_dir.name
                project_name, project_path = extract_project_from_slug(project_slug)

                for session_dir in project_dir.iterdir():
                    if not session_dir.is_dir():
                        continue

                    session_id = session_dir.name
                    if session_id in found_ids:
                        continue

                    summary_path = session_dir / "session-memory" / "summary.md"
                    if not summary_path.exists():
                        continue

                    try:
                        mtime = summary_path.stat().st_mtime
                    except OSError:
                        continue

                    if mtime > watermark_ts:
                        self._session_refs.append(
                            {
                                "session_id": session_id,
                                "project_name": project_name,
                                "project_path": project_path,
                                "summary_path": str(summary_path),
                                "mtime": mtime,
                            }
                        )
                        found_ids.add(session_id)

        except OSError as exc:
            logger.debug("Error scanning sessions: %s", exc)

    # ------------------------------------------------------------------
    # Check-in bundle
    # ------------------------------------------------------------------

    def get_pending(self) -> Dict[str, Any]:
        """Return accumulated context for the check_in tool.

        Reads session summaries lazily (on demand, not during accumulate).
        """
        sessions = []
        for ref in self._session_refs:
            entry: Dict[str, Any] = {
                "session_id": ref["session_id"],
                "project": ref["project_name"],
                "project_path": ref["project_path"],
            }
            # Lazy-load the summary content
            summary_path = Path(ref["summary_path"])
            if summary_path.exists():
                try:
                    entry["summary"] = summary_path.read_text(encoding="utf-8").strip()
                except OSError:
                    entry["summary"] = "(unable to read summary)"
            else:
                entry["summary"] = "(summary file not found)"

            sessions.append(entry)

        return {
            "sessions_since_last": sessions,
            "staged_items": list(self._staged_items),
            "last_check_in": self._last_check_in.isoformat(),
        }

    def mark_checked_in(self) -> None:
        """Advance the watermark to now and clear accumulated items."""
        self._last_check_in = datetime.now(timezone.utc)
        self._staged_items.clear()
        self._session_refs.clear()
        self._save_state()

    def stage_item(self, content: str) -> None:
        """Add a manually staged item to the pending list."""
        self._staged_items.append(
            {
                "content": content,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        self._save_state()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load_state(self) -> None:
        """Load watermark and staged items from state.json."""
        if not self._state_file.exists():
            return
        try:
            data = json.loads(self._state_file.read_text(encoding="utf-8"))
            if "last_check_in" in data:
                self._last_check_in = datetime.fromisoformat(data["last_check_in"])
            if "staged_items" in data:
                self._staged_items = data["staged_items"]
        except (json.JSONDecodeError, OSError, ValueError) as exc:
            logger.debug("Failed to load accumulator state: %s", exc)

    def _save_state(self) -> None:
        """Persist watermark and staged items to state.json."""
        try:
            data = {
                "last_check_in": self._last_check_in.isoformat(),
                "staged_items": self._staged_items,
            }
            self._state_file.write_text(
                json.dumps(data, indent=2),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.debug("Failed to save accumulator state: %s", exc)
