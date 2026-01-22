# Claude Status Overlay

## What This Is

A standalone floating desktop overlay that shows Claude's current status (idle/thinking/running/waiting) with an animated ASCII avatar. Built as a Swift app with always-on-top window.

**Location:** `/Users/shepardxia/Desktop/directory/central-hub/`

## Current Architecture (Hook-Based)

```
Claude Code Hooks (PreToolUse, PostToolUse, Stop, etc.)
    ↓ trigger
~/.claude/hooks/status-hook.sh
    ↓ writes to
/tmp/claude-status.json
    ↓ read by
ClaudeStatusOverlay.swift (floating window, polls every 0.5s)
```

**Status Flow:**
| Hook Event | Status | Color | Text |
|------------|--------|-------|------|
| UserPromptSubmit | thinking | yellow | "Thinking..." |
| PreToolUse | running | green | [tool name] |
| PostToolUse | thinking | yellow | "Thinking..." |
| Stop | idle | gray | "Idle" |
| Notification[*] | awaiting | blue | "Waiting for..." |

**Note:** Awaiting status auto-transitions to idle after 5 minutes of inactivity.

## Key Files

- `Display.swift` - Display layer: status model, avatar components, context bar, view rendering
- `ClaudeStatusOverlay.swift` - App layer: window management, file watcher, lifecycle
- `ClaudeStatusOverlay` - Compiled binary (auto-updates on restart)
- `restart.sh` - Build and restart script
- `~/.claude/hooks/status-hook.sh` - Maps hook events to status JSON
- `~/.claude/settings.json` - Hook configuration
- `docs/plans/` - Design and implementation reference

## Avatar Design

Composable system with separate components (eyes, mouth, border, substrate):

```
IDLE:           THINKING:       WORKING:        AWAITING:       OFFLINE:
╭─────────╮     ╭~~~~~~~~~╮     ╭═════════╮     ╭⋯⋯⋯⋯⋯⋯⋯⋯⋯╮     ╭·········╮
│  ·   ·  │     │  ˘   ˘  │     │  ●   ●  │     │  ?   ?  │     │  ·   ·  │
│    ◡    │     │    ~    │     │    ◡    │     │    ·    │     │    ─    │
│         │     │         │     │         │     │         │     │         │
│ ·  ·  · │     │ • ◦ • ◦ │     │ • ● • ● │     │ · · · · │     │  · · ·  │
╰─────────╯     ╰~~~~~~~~~╯     ╰═════════╯     ╰⋯⋯⋯⋯⋯⋯⋯⋯⋯╯     ╰·········╯
 █████░░░░       ████░░░░░       ███████░░       ██░░░░░░░       ░░░░░░░░░
```

**Font width fix:** Some Unicode chars (◠, ∴, ∵, ⊹, ✧) render narrower than monospace width in AppKit. Replaced with correctly-sized alternatives (˘, ·, •, ◦, ●).

## Features

- **Instant status updates** via Claude Code hooks (no transcript parsing)
- Auto-hide after 10 min idle
- Reappear at default position when active
- Draggable window
- Single instance lock
- Border pulse animation (fast for running, gentle for thinking)
- Substrate animation (4-frame smooth oscillation)

## Build & Run

```bash
# Kill existing, rebuild, launch
pkill -f ClaudeStatusOverlay
rm -f /tmp/claude-status-overlay.lock
cd "/Users/shepardxia/Desktop/directory/central-hub"
swiftc -o ClaudeStatusOverlay Display.swift ClaudeStatusOverlay.swift -framework Cocoa
./ClaudeStatusOverlay &
```

Or use the restart script:
```bash
./restart.sh
```

## Hook Configuration

Located in `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]}],
    "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]}],
    "UserPromptSubmit": [{"matcher": "*", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]}],
    "Stop": [{"matcher": "*", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]}],
    "Notification": [
      {"matcher": "permission_prompt", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]},
      {"matcher": "idle_prompt", "hooks": [{"type": "command", "command": "/Users/shepardxia/.claude/hooks/status-hook.sh"}]}
    ]
  }
}
```

**Note:** Hooks require Claude Code session restart to take effect.

## Testing

```bash
# Test hook script manually
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash"}' | ~/.claude/hooks/status-hook.sh
cat /tmp/claude-status.json
# Expected: {"status":"running","tool":"Bash","color":"green","text":"Bash","timestamp":...}

# Test different states
echo '{"hook_event_name":"Stop"}' | ~/.claude/hooks/status-hook.sh
echo '{"hook_event_name":"Notification","notification_type":"permission_prompt"}' | ~/.claude/hooks/status-hook.sh
```

## Completed Enhancements

- **File watching** - DispatchSource for instant updates (no polling)
- **Awaiting avatar** - `?` eyes with blue ellipsis border for notifications
- **Context bar** - High-contrast █/░ progress bar below avatar
- **5-min timeout** - Awaiting auto-transitions to idle

## Pending Enhancements

1. **LaunchAgent** - Auto-start on login (`~/Library/LaunchAgents/com.claude.status-overlay.plist`)
