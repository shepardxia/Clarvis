#!/usr/bin/env python3
"""
Thinking feed parser - adapted from watch-claude-think by @bporterfield
https://github.com/bporterfield/watch-claude-think
Licensed under MIT. Ported from TypeScript to Python for clarvis integration.
"""

import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import asyncio

    from ..core.context import AppContext


class SessionStatus(Enum):
    ACTIVE = "active"
    IDLE = "idle"
    ENDED = "ended"


@dataclass
class ThinkingBlock:
    """A single thinking block extracted from an assistant message."""

    text: str
    timestamp: str
    session_id: str
    message_id: str = ""


@dataclass
class SessionState:
    """State of a single Claude Code session."""

    session_id: str
    project: str
    project_path: str
    file_path: Path
    status: SessionStatus = SessionStatus.ACTIVE
    last_activity: datetime = field(default_factory=datetime.now)
    thoughts: list[ThinkingBlock] = field(default_factory=list)
    file_position: int = 0  # Track read position for incremental parsing

    def add_thought(self, thought: ThinkingBlock, max_thoughts: int = 50):
        """Add thought, keeping only most recent max_thoughts."""
        self.thoughts.append(thought)
        if len(self.thoughts) > max_thoughts:
            self.thoughts = self.thoughts[-max_thoughts:]
        self.last_activity = datetime.now()
        self.status = SessionStatus.ACTIVE

    def get_recent_thoughts(self, limit: int = 10) -> list[ThinkingBlock]:
        """Get the N most recent thoughts."""
        return self.thoughts[-limit:] if self.thoughts else []


def parse_jsonl_line(line: str) -> dict | None:
    """Parse a single JSONL line, handling malformed/incomplete lines."""
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def extract_thinking_blocks(entry: dict) -> list[ThinkingBlock]:
    """
    Extract thinking blocks from a JSONL entry.

    Ported from watch-claude-think parser.ts logic:
    - Only assistant messages have thinking blocks
    - Skip sidechain messages
    - Extract from content array where type === "thinking"
    """
    # Only assistant messages have thinking
    if entry.get("type") != "assistant":
        return []

    # Skip sidechain messages (parallel explorations)
    if entry.get("isSidechain"):
        return []

    message = entry.get("message", {})
    content = message.get("content", [])

    # Content might be a string (no thinking) or array (may have thinking)
    if isinstance(content, str):
        return []

    blocks = []
    session_id = entry.get("sessionId", "")
    timestamp = entry.get("timestamp", "")
    message_id = entry.get("uuid", "")

    for i, item in enumerate(content):
        if isinstance(item, dict) and item.get("type") == "thinking":
            thinking_text = item.get("thinking", "")
            if thinking_text:
                blocks.append(
                    ThinkingBlock(
                        text=thinking_text,
                        timestamp=timestamp,
                        session_id=session_id,
                        message_id=f"{message_id}:{i}",
                    )
                )

    return blocks


def is_session_stop_event(entry: dict) -> bool:
    """
    Check if entry indicates session has stopped.

    Ported from watch-claude-think: looks for Stop hook events.
    """
    if entry.get("type") != "progress":
        return False

    data = entry.get("data", {})
    if data.get("type") == "hook_progress":
        hook_event = data.get("hookEvent", "")
        if hook_event == "Stop":
            return True

    return False


def extract_project_from_path(file_path: Path) -> tuple[str, str]:
    """Extract project name and path from session file location.

    Delegates to the filesystem-aware ``extract_project_from_slug``
    which handles hyphenated directory names correctly.
    """
    from .context_accumulator import extract_project_from_slug

    project_slug = file_path.parent.name
    return extract_project_from_slug(project_slug)


# Constants
IDLE_TIMEOUT_SECONDS = 600  # 10 minutes
ENDED_GRACE_PERIOD_SECONDS = 30  # Keep ended sessions briefly for final queries


class SessionManager:  # pragma: no cover
    """
    Manages all active Claude Code sessions.

    Adapted from watch-claude-think session-manager.ts:
    - Watches ~/.claude/projects/ for session files
    - Tracks thinking blocks per session
    - Manages session lifecycle (active -> idle -> ended)
    """

    def __init__(self):
        self.sessions: dict[str, SessionState] = {}
        self._lock = threading.Lock()
        self._known_files: dict[Path, float] = {}  # path -> last mtime

    def connect(self, ctx: "AppContext") -> None:
        """Subscribe to hook:event for signal-driven transcript processing."""
        self._ctx = ctx
        ctx.bus.on("hook:event", self._on_hook_event)

    def _on_hook_event(self, signal: str, *, transcript_path: str = None, **_kw) -> None:
        if transcript_path:
            fut = self._ctx.loop.run_in_executor(None, self.process_transcript, transcript_path)
            fut.add_done_callback(self._log_executor_error)

    @staticmethod
    def _log_executor_error(fut: "asyncio.Future") -> None:
        if exc := fut.exception():
            logger.exception("Error processing transcript", exc_info=exc)

    def _process_session_file(self, file_path: Path):
        """Process a session file, extracting new thinking blocks."""
        session_id = file_path.stem  # UUID is the filename without .jsonl

        with self._lock:
            # Get or create session state
            if session_id not in self.sessions:
                project_name, project_path = extract_project_from_path(file_path)
                self.sessions[session_id] = SessionState(
                    session_id=session_id,
                    project=project_name,
                    project_path=project_path,
                    file_path=file_path,
                )

            session = self.sessions[session_id]

            # Skip ended sessions
            if session.status == SessionStatus.ENDED:
                return

            # Read new content from file
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    file_size = f.seek(0, 2)  # get current file size
                    if session.file_position > file_size:
                        session.file_position = 0  # file was truncated
                    f.seek(session.file_position)
                    new_content = f.read()
                    session.file_position = f.tell()
            except (IOError, OSError):
                return

            # Parse new lines
            for line in new_content.split("\n"):
                entry = parse_jsonl_line(line)
                if entry is None:
                    continue

                # Check for stop event
                if is_session_stop_event(entry):
                    session.status = SessionStatus.ENDED
                    continue

                # Extract thinking blocks
                blocks = extract_thinking_blocks(entry)
                for block in blocks:
                    session.add_thought(block)

    def process_transcript(self, transcript_path: str) -> None:
        """Process a single transcript file on demand (signal-driven).

        Called when a hook event arrives with a transcript_path. Skips the
        global directory scan — only processes the specific file that changed.
        """
        path = Path(transcript_path)
        if not path.exists() or path.suffix != ".jsonl":
            return
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime != self._known_files.get(path):
            self._known_files[path] = mtime
            self._process_session_file(path)

    def poll_sessions(self) -> None:
        """Clean up stale sessions.

        Lifecycle-only — file processing is now signal-driven via
        process_transcript(). Called periodically by Scheduler at a
        relaxed interval.
        """
        now = datetime.now()
        to_remove = []

        with self._lock:
            for session_id, session in self.sessions.items():
                idle_seconds = (now - session.last_activity).total_seconds()

                if session.status == SessionStatus.ACTIVE:
                    if idle_seconds > IDLE_TIMEOUT_SECONDS:
                        session.status = SessionStatus.ENDED

                elif session.status == SessionStatus.ENDED:
                    if idle_seconds > IDLE_TIMEOUT_SECONDS + ENDED_GRACE_PERIOD_SECONDS:
                        to_remove.append(session_id)

            for session_id in to_remove:
                del self.sessions[session_id]

    # --- Public query methods ---

    def list_active_sessions(self) -> list[dict]:
        """List all active sessions with metadata."""
        with self._lock:
            result = []
            for session in self.sessions.values():
                result.append(
                    {
                        "session_id": session.session_id,
                        "project": session.project,
                        "project_path": session.project_path,
                        "status": session.status.value,
                        "last_activity": session.last_activity.isoformat(),
                        "thought_count": len(session.thoughts),
                    }
                )
            # Sort by last activity (most recent first)
            result.sort(key=lambda x: x["last_activity"], reverse=True)
            return result

    def get_session_thoughts(self, session_id: str, limit: int = 10) -> dict | None:
        """Get thoughts for a specific session."""
        with self._lock:
            session = self.sessions.get(session_id)
            if session is None:
                return None

            thoughts = session.get_recent_thoughts(limit)
            return {
                "session_id": session.session_id,
                "project": session.project,
                "project_path": session.project_path,
                "status": session.status.value,
                "thoughts": [{"text": t.text, "timestamp": t.timestamp} for t in thoughts],
            }

    def get_latest_thought(self) -> dict | None:
        """Get the single most recent thought across all sessions."""
        with self._lock:
            latest = None
            latest_time = ""

            for session in self.sessions.values():
                if session.thoughts:
                    last_thought = session.thoughts[-1]
                    if last_thought.timestamp > latest_time:
                        latest_time = last_thought.timestamp
                        latest = {
                            "session_id": session.session_id,
                            "project": session.project,
                            "text": last_thought.text,
                            "timestamp": last_thought.timestamp,
                        }

            return latest


# Global session manager instance
_session_manager: SessionManager | None = None


def get_session_manager() -> SessionManager:  # pragma: no cover
    """Get or create the global session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
    return _session_manager
