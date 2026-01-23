#!/usr/bin/env python3
"""
Thinking feed parser - adapted from watch-claude-think by @bporterfield
https://github.com/bporterfield/watch-claude-think
Licensed under MIT. Ported from TypeScript to Python for central-hub integration.
"""

import json
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent


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
                blocks.append(ThinkingBlock(
                    text=thinking_text,
                    timestamp=timestamp,
                    session_id=session_id,
                    message_id=f"{message_id}:{i}",
                ))

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
    """
    Extract project name and path from session file location.

    Session files are at: ~/.claude/projects/{project-slug}/{session-id}.jsonl
    Project slug is path with slashes replaced by dashes.
    """
    # Parent directory is the project slug
    project_slug = file_path.parent.name

    # Convert slug back to path (dashes to slashes, strip leading dash)
    if project_slug.startswith("-"):
        project_path = "/" + project_slug[1:].replace("-", "/")
    else:
        project_path = project_slug.replace("-", "/")

    # Project name is last component
    project_name = Path(project_path).name or project_slug

    return project_name, project_path


# Constants
CLAUDE_PROJECTS_DIR = Path.home() / ".claude" / "projects"
IDLE_TIMEOUT_SECONDS = 600  # 10 minutes
ENDED_GRACE_PERIOD_SECONDS = 30  # Keep ended sessions briefly for final queries


class JsonlFileHandler(FileSystemEventHandler):
    """Handle .jsonl file changes."""

    def __init__(self, callback):
        self.callback = callback

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".jsonl"):
            self.callback(Path(event.src_path))

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(".jsonl"):
            self.callback(Path(event.src_path))


class SessionManager:
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
        self._observer: Observer | None = None
        self._lifecycle_thread: threading.Thread | None = None
        self._running = False

    def start(self):
        """Start watching for session files and managing lifecycle."""
        if self._running:
            return

        self._running = True

        # Initial scan for existing sessions
        self._scan_existing_sessions()

        # Start file watcher
        self._observer = Observer()
        handler = JsonlFileHandler(self._on_file_change)

        if CLAUDE_PROJECTS_DIR.exists():
            self._observer.schedule(handler, str(CLAUDE_PROJECTS_DIR), recursive=True)
            self._observer.start()

        # Start lifecycle management thread
        self._lifecycle_thread = threading.Thread(target=self._lifecycle_loop, daemon=True)
        self._lifecycle_thread.start()

    def stop(self):
        """Stop watching and cleanup."""
        self._running = False

        if self._observer:
            self._observer.stop()
            self._observer.join(timeout=2)
            self._observer = None

    def _scan_existing_sessions(self):
        """Scan for existing session files on startup."""
        if not CLAUDE_PROJECTS_DIR.exists():
            return

        for jsonl_file in CLAUDE_PROJECTS_DIR.glob("*/*.jsonl"):
            self._process_session_file(jsonl_file)

    def _on_file_change(self, file_path: Path):
        """Handle file change notification."""
        self._process_session_file(file_path)

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
                with open(file_path, "r") as f:
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

    def _lifecycle_loop(self):
        """Background loop to manage session lifecycle."""
        while self._running:
            time.sleep(30)  # Check every 30 seconds

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
                result.append({
                    "session_id": session.session_id,
                    "project": session.project,
                    "project_path": session.project_path,
                    "status": session.status.value,
                    "last_activity": session.last_activity.isoformat(),
                    "thought_count": len(session.thoughts),
                })
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
                "thoughts": [
                    {"text": t.text, "timestamp": t.timestamp}
                    for t in thoughts
                ],
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


def get_session_manager() -> SessionManager:
    """Get or create the global session manager."""
    global _session_manager
    if _session_manager is None:
        _session_manager = SessionManager()
        _session_manager.start()
    return _session_manager
