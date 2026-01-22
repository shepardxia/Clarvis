# Thinking Feed Adaptation Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Adapt watch-claude-think's parser to add session-aware thinking monitoring to central-hub's MCP server.

**Architecture:** Port the JSONL parser from watch-claude-think (TypeScript) to Python, add file watching with watchdog, expose three MCP tools for querying thinking data across all Claude Code sessions. Track session lifecycle via explicit Stop events with idle timeout fallback.

**Tech Stack:** Python 3.10+, watchdog (file monitoring), FastMCP, existing central-hub MCP server

**Attribution:** Adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by @bporterfield (MIT License)

---

## Task 1: Add watchdog dependency

**Files:**
- Modify: `mcp-server/pyproject.toml:6-9`

**Step 1: Update pyproject.toml**

```toml
[project]
name = "central-hub"
version = "0.1.0"
description = "Central MCP server for widget data (weather, status, etc.)"
requires-python = ">=3.10"
dependencies = [
    "mcp>=1.0.0",
    "requests>=2.28.0",
    "watchdog>=3.0.0",
]

[build-system]
requires = ["setuptools"]
build-backend = "setuptools.build_meta"
```

**Step 2: Reinstall dependencies**

Run: `cd ~/.claude/mcp-servers/central-hub && source venv/bin/activate && pip install -e .`
Expected: Successfully installed watchdog

**Step 3: Commit**

```bash
git add mcp-server/pyproject.toml
git commit -m "deps: add watchdog for file system monitoring"
```

---

## Task 2: Create data models

**Files:**
- Create: `mcp-server/thinking_feed.py`

**Step 1: Create thinking_feed.py with data models**

```python
#!/usr/bin/env python3
"""
Thinking feed parser - adapted from watch-claude-think by @bporterfield
https://github.com/bporterfield/watch-claude-think
Licensed under MIT. Ported from TypeScript to Python for central-hub integration.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path


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
```

**Step 2: Verify syntax**

Run: `cd ~/Desktop/directory/central-hub && python3 -m py_compile mcp-server/thinking_feed.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add mcp-server/thinking_feed.py
git commit -m "feat: add thinking feed data models

Adapted from watch-claude-think by @bporterfield (MIT License)"
```

---

## Task 3: Implement JSONL parser

**Files:**
- Modify: `mcp-server/thinking_feed.py`

**Step 1: Add parser functions**

Add after the `SessionState` class:

```python
import json


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
```

**Step 2: Verify syntax**

Run: `cd ~/Desktop/directory/central-hub && python3 -m py_compile mcp-server/thinking_feed.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add mcp-server/thinking_feed.py
git commit -m "feat: add JSONL parser for thinking blocks

Ported from watch-claude-think parser.ts:
- Parse assistant messages for thinking content
- Skip sidechain messages
- Detect Stop events for session lifecycle"
```

---

## Task 4: Implement SessionManager

**Files:**
- Modify: `mcp-server/thinking_feed.py`

**Step 1: Add SessionManager class**

Add after the parser functions:

```python
import threading
import time
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent


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
```

**Step 2: Verify syntax**

Run: `cd ~/Desktop/directory/central-hub && python3 -m py_compile mcp-server/thinking_feed.py`
Expected: No output (success)

**Step 3: Commit**

```bash
git add mcp-server/thinking_feed.py
git commit -m "feat: add SessionManager for multi-session tracking

- File watching with watchdog
- Session lifecycle (active -> idle -> ended)
- 10-minute idle timeout with 30s grace period
- Query methods for MCP tools"
```

---

## Task 5: Add MCP tools to server.py

**Files:**
- Modify: `mcp-server/server.py`

**Step 1: Add import at top of server.py**

After the existing imports (around line 11), add:

```python
from thinking_feed import get_session_manager
```

**Step 2: Add three new MCP tools**

Add before the `# --- Background refresh function ---` comment (around line 303):

```python
# --- Thinking Feed Tools ---
# Adapted from watch-claude-think by @bporterfield (MIT License)
# https://github.com/bporterfield/watch-claude-think


@mcp.tool()
async def list_active_sessions() -> list[dict]:
    """
    List all active Claude Code sessions across all projects.

    Returns list of sessions with metadata including project name,
    status (active/idle/ended), and thought count.
    """
    manager = get_session_manager()
    return manager.list_active_sessions()


@mcp.tool()
async def get_session_thoughts(session_id: str, limit: int = 10) -> dict:
    """
    Get recent thinking blocks from a specific session.

    Args:
        session_id: UUID of the session
        limit: Maximum number of thoughts to return (default: 10)

    Returns:
        Session info with list of recent thoughts, or error if not found
    """
    manager = get_session_manager()
    result = manager.get_session_thoughts(session_id, limit)
    if result is None:
        return {"error": f"Session {session_id} not found"}
    return result


@mcp.tool()
async def get_latest_thought() -> dict:
    """
    Get the single most recent thought across all sessions.

    Returns:
        Latest thought with session context, or empty dict if none
    """
    manager = get_session_manager()
    result = manager.get_latest_thought()
    if result is None:
        return {"message": "No active thoughts found"}
    return result
```

**Step 3: Verify syntax**

Run: `cd ~/Desktop/directory/central-hub && python3 -m py_compile mcp-server/server.py`
Expected: No output (success)

**Step 4: Commit**

```bash
git add mcp-server/server.py
git commit -m "feat: add thinking feed MCP tools

- list_active_sessions(): List all Claude sessions
- get_session_thoughts(session_id, limit): Get thoughts from session
- get_latest_thought(): Get most recent thought globally

Adapted from watch-claude-think by @bporterfield (MIT License)"
```

---

## Task 6: Update setup.sh to copy new file

**Files:**
- Modify: `setup.sh:76-77`

**Step 1: Update setup_mcp_server function**

Find the line that copies server.py (around line 76) and add the new file:

```bash
    # Copy server files
    cp "$MCP_SOURCE/server.py" "$MCP_DEST/"
    cp "$MCP_SOURCE/thinking_feed.py" "$MCP_DEST/"
    cp "$MCP_SOURCE/pyproject.toml" "$MCP_DEST/"
    print_success "Copied MCP server to $MCP_DEST"
```

**Step 2: Test setup script**

Run: `cd ~/Desktop/directory/central-hub && ./setup.sh`
Expected: Setup completes successfully, thinking_feed.py copied

**Step 3: Commit**

```bash
git add setup.sh
git commit -m "build: copy thinking_feed.py in setup"
```

---

## Task 7: Update README with credits

**Files:**
- Modify: `README.md`

**Step 1: Add Credits section before "See Also"**

Find the "## See Also" section (around line 334) and add before it:

```markdown
## Credits

- **Thinking Feed** - Adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by [@bporterfield](https://github.com/bporterfield) (MIT License). Ported from TypeScript to Python for MCP integration.

---

## See Also
```

**Step 2: Update Tools table**

Find the Tools table in the MCP Server section (around line 110) and add new tools:

```markdown
### Tools I Provide

| Tool | Description | Dependencies |
|------|-------------|--------------|
| `ping()` | Test server connectivity | None |
| `get_weather(lat?, lon?)` | Current weather with auto-location | `requests` (included) |
| `get_time(timezone?)` | Current time in any timezone | None (stdlib zoneinfo) |
| `get_claude_status()` | Read my current status | None |
| `list_active_sessions()` | List all active Claude Code sessions | `watchdog` (included) |
| `get_session_thoughts(id, limit?)` | Get thinking blocks from a session | `watchdog` (included) |
| `get_latest_thought()` | Get most recent thought globally | `watchdog` (included) |
```

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add credits for watch-claude-think adaptation"
```

---

## Task 8: Integration test

**Files:**
- None (manual testing)

**Step 1: Reinstall MCP server**

Run: `cd ~/Desktop/directory/central-hub && ./setup.sh`
Expected: Setup completes with new dependencies

**Step 2: Restart Claude Code**

Close and reopen Claude Code to reload MCP server.

**Step 3: Test list_active_sessions**

Ask Claude: "List my active sessions"
Expected: Returns list with at least the current session

**Step 4: Test get_latest_thought**

Ask Claude: "What's my latest thought?"
Expected: Returns a thought from this session (or "No active thoughts" if thinking is disabled)

**Step 5: Test get_session_thoughts**

Ask Claude: "Get thoughts from session [paste session_id from step 3]"
Expected: Returns list of recent thoughts

**Step 6: Final commit**

```bash
git add -A
git commit -m "feat: complete thinking feed integration

Adapted from watch-claude-think by @bporterfield (MIT License)
- Session-aware thinking monitoring across all projects
- Automatic session lifecycle management
- Three MCP tools for querying thinking data"
```

---

## Future Work (Phase 2: Display)

Options noted for later implementation:

- **A) Rotating carousel** - Cycle through sessions in widget
- **B) Most recent thought** - Single active session display (recommended)
- **C) Aggregated feed** - Scrolling list of all thoughts

Widget changes would go in `Display.swift` and read from a new `/tmp/central-hub-thinking.json` file.
