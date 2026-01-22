# Central Hub Integration Patterns & Insights

## Project Architecture Summary

Central Hub is a bi-directional integration system:

```
User Development (Desktop)
  ↓ (edit & test)
/Users/shepardxia/Desktop/directory/central-hub/
  ├─ source: control-panel.html, server.py, usage_monitor.py
  ├─ runs: control-server.py locally
  ├─ outputs: sync-to-mcp.sh (deployment)
  ↓
MCP Server Installation (~/.claude/mcp-servers/central-hub/)
  ├─ used by: Claude Code IDE
  ├─ provides: 5 MCP tools (ping, weather, time, status, usage_stats)
  ├─ outputs: /tmp/central-hub-*.json (widget data files)
  ↓
Desktop Widget (ClaudeStatusOverlay)
  ├─ reads: /tmp files
  ├─ renders: animated ASCII avatar + weather effects
  ├─ updates: via Claude Code hooks (PreToolUse, Stop, etc.)
```

## Key Patterns

### 1. Source of Truth Workflow

**Rule:** Always edit files in `~/Desktop/directory/central-hub/` first.

**Why:** Keeps changes under git control, allows testing before deployment, enables version history.

**Deployment:** Use `./sync-to-mcp.sh` to copy changes to `~/.claude/mcp-servers/central-hub/`

**Files synced:**
- `mcp-server/server.py` → `~/.claude/mcp-servers/central-hub/server.py`
- `mcp-server/usage_monitor.py` → `~/.claude/mcp-servers/central-hub/usage_monitor.py`
- `control-panel.html` → `~/.claude/mcp-servers/central-hub/control-panel.html`
- `control-server.py` → `~/.claude/mcp-servers/central-hub/control-server.py`

### 2. Widget Data File Pattern

All MCP tools write to `/tmp/central-hub-*.json` for widget consumption:

**Schema consistency (all files include):**
```json
{
  "status": "success" | "error" | "no_data",
  "timestamp": "2026-01-22T13:47:09.874086",
  ...data...
}
```

**Benefits:**
- Widgets check `timestamp` for freshness
- Consistent error handling across all data sources
- Easy to add new data sources (same pattern)

**Files:**
- `/tmp/central-hub-weather.json` - Temperature, wind, conditions
- `/tmp/central-hub-time.json` - Current time, timezone, date
- `/tmp/central-hub-usage-stats.json` - Tokens, costs, burn rates
- `/tmp/claude-status.json` - Claude's running status (hook-based)

### 3. MCP Tool Integration Pattern

Each tool follows this pattern:

```python
@mcp.tool()
async def get_something() -> str:
    """Tool description."""
    try:
        data = calculate_or_fetch_data()

        widget_file = Path("/tmp/central-hub-something.json")
        widget_data = {
            "status": "success",
            "timestamp": datetime.now().isoformat(),
            ...data...
        }
        widget_file.write_text(json.dumps(widget_data, indent=2))

        return f"Human-readable summary: {data}"
    except Exception as e:
        return f"Error: {e}"
```

**Key points:**
- Always write widget file (even if tool crashes)
- Always include timestamp
- Return human-readable string (for Claude's display)
- Write JSON for widget consumption

### 4. Optional Dependencies Pattern

When integrating external packages (like claude-monitor):

```python
def get_data():
    try:
        from external_package import something
        # use it
        return {"status": "success", "data": ...}
    except ImportError:
        return {
            "status": "error",
            "error_message": "external_package not installed"
        }
```

**Benefits:**
- Central-hub works without optional dependencies
- Graceful degradation (UI shows "not installed" instead of crashing)
- Users can incrementally add features (install claude-monitor when needed)

### 5. Control Panel Data Binding Pattern

The control panel HTML uses this pattern:

```javascript
async function loadWidgetData() {
    const widgets = ['weather', 'time', 'usage', 'status'];

    for (const widget of widgets) {
        try {
            const file = `/tmp/central-hub-${widget}.json`;
            const data = await fetch(file).then(r => r.json());

            document.getElementById(`${widget}Data`).textContent =
                JSON.stringify(data, null, 2);
        } catch (err) {
            // handle error
        }
    }
}
```

**Benefits:**
- Single source of truth (reads /tmp files that MCP tools write)
- Auto-refresh every 30 seconds
- Live data preview without reloading
- Easy to add new data sources

## Integration Insights

### Pattern 1: Graceful Degradation
Central-hub is resilient by design:
- Missing optional packages? Return helpful error message
- File doesn't exist? Show "Loading..." or "Error: File not found"
- API call fails? Return status: "error" with message

This keeps the whole system usable even when parts fail.

### Pattern 2: Data Files as API
Instead of internal APIs, use `/tmp/` JSON files:
- **Pro:** Widget can read same files as control panel
- **Pro:** Easy to debug (just read JSON file)
- **Pro:** No process-to-process communication complexity
- **Con:** Slower than memory (but acceptable for UI data)

### Pattern 3: Separation of Concerns

| Component | Responsibility | Output |
|-----------|-----------------|--------|
| MCP Server (server.py) | Compute metrics, call APIs | `/tmp/*.json` + MCP tool return |
| usage_monitor.py | Claude-monitor integration | Wrapped stats object |
| Control Panel (HTML) | Display + user control | Config JSON to /tmp |
| Widget (Swift) | Render + animate | Screen display |

Each component is independent and can be updated separately.

### Pattern 4: Two-Phase Data Flow

1. **MCP Phase:** When Claude calls a tool
   - `server.py` computes data
   - Writes `/tmp/central-hub-*.json` (async for widget)
   - Returns string to Claude

2. **Widget Phase:** Periodic refresh
   - Widget reads `/tmp/central-hub-*.json`
   - Renders animated display
   - Zero communication with MCP server

This is event-driven for MCP, pull-based for widget.

## Future Integration Ideas

### Easy Additions
- **System metrics** - CPU, memory, disk (add `get_system_stats()` tool)
- **Git status** - Current branch, uncommitted files (add `get_git_status()` tool)
- **Pomodoro timer** - Add to status overlay
- **Custom alerts** - Temperature warnings, package delivery, etc.

### Medium Complexity
- **Persistent settings database** - Instead of just /tmp, store in SQLite
- **Widget theme switcher** - Add to control panel, read theme from config
- **MCP tool documentation** - Auto-generate from docstrings

### Advanced
- **Bidirectional sync** - Widget can trigger MCP tools (hold to refresh)
- **Data retention** - Store historical metrics in database
- **Aggregate reporting** - Weekly/monthly summaries
- **Custom plugins** - Let users add tools without modifying server.py

## Code Quality Patterns

### Verified Approaches

✓ **Exception handling:** Try/except with graceful fallbacks
✓ **Type hints:** Used in Python for IDE support
✓ **Documentation:** Docstrings + clear variable names
✓ **Testing:** Manual testing via control panel (live verification)
✓ **Logging:** Print statements (simple, works for background processes)

### To Avoid

✗ **Hardcoded paths** - Use Path() or environment variables
✗ **Silent failures** - Always log or return error status
✗ **Nested try/except** - Extract to helper functions
✗ **Magic numbers** - Use named constants
✗ **N+1 queries** - Cache results when fetching from APIs

## Debugging Workflow

### When widget doesn't update:
1. Check `/tmp/central-hub-*.json` exists and has recent timestamp
2. Check widget process is running: `ps aux | grep ClaudeStatusOverlay`
3. Check hooks are installed: `cat ~/.claude/settings.json | grep hooks`
4. Manually trigger hook: `echo '{"hook_event_name":"Stop"}' | ~/.claude/hooks/status-hook.sh`

### When MCP tool fails:
1. Test manually: `~/.claude/mcp-servers/central-hub/venv/bin/python3 server.py --refresh`
2. Check /tmp file was created: `cat /tmp/central-hub-*.json`
3. Check imports work: `python3 -c "from usage_monitor import get_claude_monitor_stats"`

### When control panel won't load:
1. Start control server: `python3 control-server.py`
2. Check runs: `curl http://localhost:8765/control-panel`
3. Check logs: control server prints all requests

## Deployment Checklist

Before pushing changes:

- [ ] Tested changes in `~/Desktop/directory/central-hub/` first
- [ ] Used `./sync-to-mcp.sh` to deploy to MCP server
- [ ] Verified MCP tool works: `python3 server.py --refresh`
- [ ] Checked `/tmp/central-hub-*.json` has new data
- [ ] Tested control panel: `http://localhost:8765`
- [ ] Committed changes to git: `git add -A && git commit -m "..."`
- [ ] Pushed to remote: `git push`

## Architecture Decision Record

### Why Not Use Processes for IPC?
**Considered:** Direct process-to-process communication (sockets, pipes)
**Chosen:** JSON files in /tmp
**Reason:** Simplicity - no connection management, no serialization overhead, easier to debug

### Why Control Panel on Local HTTP?
**Considered:** Direct Swift UI, native app UI
**Chosen:** HTML control panel (HTTP-served)
**Reason:** Cross-platform testability, fast iteration, browser DevTools debugging

### Why usage_monitor Integration Is Optional?
**Considered:** Hard dependency on claude-monitor
**Chosen:** Graceful ImportError handling
**Reason:** Keeps central-hub lightweight, lets users opt-in to usage tracking

### Why Two-Phase Data Flow?
**Considered:** Widget querying MCP server directly
**Chosen:** MCP writes files, widget reads files asynchronously
**Reason:** Decouples MCP server from widget update rate, prevents slowdowns in Claude

---

**Last Updated:** 2026-01-22
**Related Files:** README.md (setup), CLAUDE.md (project context), control-panel.html (UI), server.py (core logic)
