# Data-Pixels Visualizer Design

**Date:** 2026-01-22
**Status:** Proposed
**Replaces:** ASCII avatar rendering in current Swift overlay

## Goals

1. **Richer visuals** - Expressive 8-bit pixel art instead of ASCII characters
2. **Easier iteration** - Edit sprite definitions in JS without recompiling Swift
3. **Future cross-platform** - Web-based renderer opens door to browser/Electron later

## Architecture

Hybrid Swift + WebView approach - keep existing window management, replace rendering:

```
┌─────────────────────────────────────────────────┐
│  ClaudeStatusOverlay.swift (existing)           │
│  - Window management, positioning, dragging     │
│  - File watcher for /tmp/claude-status.json     │
│  - Timeout logic (resting → idle)               │
│  - Single instance lock                         │
│                                                 │
│  ┌───────────────────────────────────────────┐  │
│  │  WKWebView (new)                          │  │
│  │  - Loads local HTML file                  │  │
│  │  - Runs Data-Pixels rendering             │  │
│  │  - Receives status via JS bridge          │  │
│  │                                           │  │
│  │  ┌─────────────────────────────────────┐  │  │
│  │  │  Pixel Art Renderer (JS)            │  │  │
│  │  │  - Sprite definitions (pixel data)  │  │  │
│  │  │  - Animation loop (requestAnimFrame)│  │  │
│  │  │  - Particle system                  │  │  │
│  │  └─────────────────────────────────────┘  │  │
│  └───────────────────────────────────────────┘  │
└─────────────────────────────────────────────────┘
```

## Sprite Design

**Size:** 32×32 pixels

**Character:** Simple robot/assistant face - geometric, friendly, expressive through eyes and color

```
Rough concept:

    ╔══════════════════╗
    ║   ┌──┐    ┌──┐   ║
    ║   │◉◉│    │◉◉│   ║  ← Eyes (change per state)
    ║   └──┘    └──┘   ║
    ║                  ║
    ║      ════        ║  ← Mouth (simple line/curve)
    ║                  ║
    ║   ▪  ▪  ▪  ▪     ║  ← Activity indicator dots
    ╚══════════════════╝
```

**Per-state variations:**

| State | Eyes | Mouth | Color Palette | Frame Count |
|-------|------|-------|---------------|-------------|
| thinking | Half-closed, looking up | Wavy `~` | Yellow/amber | 3-4 frames |
| running | Wide open, focused | Smile `◡` | Green | 2-3 frames |
| awaiting | `?` shapes | Dot `.` | Blue | 2 frames |
| resting | Closed `─ ─` | Neutral `─` | Gray | 1 frame |
| idle | (hidden) | — | — | — |

## Animation System

**Three layers rendered simultaneously:**

```
┌─────────────────────────────────────┐
│  Layer 3: Particles (top)           │  Floating ?, sparkles, Zzz
├─────────────────────────────────────┤
│  Layer 2: Sprite frames (middle)    │  The character cycling
├─────────────────────────────────────┤
│  Layer 1: Glow/background (bottom)  │  Pulsing color, ambient light
└─────────────────────────────────────┘
```

**Animation timing:**

| State | Sprite FPS | Glow Effect | Particles |
|-------|-----------|-------------|-----------|
| thinking | 2 fps (slow cycle) | Gentle yellow pulse | `...` dots cycling |
| running | 4 fps (active) | Bright green steady | Sparkles flying off |
| awaiting | 1 fps (subtle) | Blue pulse | `?` floating up |
| resting | 0 (static) | Very slow gray fade | Occasional `Z` |

**Particle effects by state:**

| State | Effect |
|-------|--------|
| thinking | Small dots/ellipsis floating near sprite |
| running | Sparkles/pixels flying off to sides |
| awaiting | Floating `?` marks, pulsing ring |
| resting | Gentle `Z`s drifting upward |
| idle | None (fades to hidden) |

## File Structure

```
central-hub/
├── ClaudeStatusOverlay.swift   # MODIFY: Replace NSTextField with WKWebView
├── Display.swift               # MODIFY: Remove ASCII art, add JS bridge
├── renderer/                   # NEW: Web-based renderer
│   ├── index.html              # Main HTML (loads Data-Pixels)
│   ├── sprites.js              # Pixel art definitions
│   ├── animator.js             # Animation loop, particle system
│   └── data-pixels.min.js      # Library (from npm)
├── ClaudeStatusOverlay         # Compiled binary
└── restart.sh                  # Unchanged
```

## Swift ↔ JavaScript Bridge

```swift
// Swift side: push status to WebView
webView.evaluateJavaScript("setState('\(status)', '\(tool)')")
```

```javascript
// JS side: receive and animate
window.setState = function(status, tool) {
  currentState = status;
  toolName = tool;
  resetAnimation();
};
```

## Iteration Workflow

1. Edit `sprites.js` - change pixel colors, add frames
2. Refresh WebView (or restart overlay)
3. See changes immediately

No Swift recompilation needed for art changes.

## Status States (unchanged)

| State | Trigger | Timeout |
|-------|---------|---------|
| thinking | User submits prompt | — |
| running | Tool executing | — |
| awaiting | Needs input | 5 min → resting |
| resting | After awaiting timeout | 10 min → idle |
| idle | After resting timeout | Hidden |

## Future Ideas

- **Terminal-based renderer** - Render pixel art as colored Unicode blocks in terminal (novel aesthetic, works over SSH)

## Implementation Steps

1. Set up `renderer/` folder with Data-Pixels
2. Create basic sprite definitions in `sprites.js`
3. Build animation loop in `animator.js`
4. Modify Swift to use WKWebView instead of NSTextField
5. Implement JS bridge for status updates
6. Add particle system
7. Polish animations and timing
