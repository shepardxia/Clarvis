<div align="center">

<pre>
 ██████╗  ██╗       █████╗  ██████╗  ██╗   ██╗ ██╗ ███████╗
██╔════╝  ██║      ██╔══██╗ ██╔══██╝ ██║   ██║ ██║ ██╔════╝
██║       ██║      ███████║ ██████╔╝ ██║   ██║ ██║ ███████╗
██║       ██║      ██╔══██║ ██╔══██╗ ╚██╗ ██╔╝ ██║ ╚════██║
╚██████╗  ███████╗ ██║  ██║ ██║  ██║  ╚████╔╝  ██║ ███████║
 ╚═════╝  ╚══════╝ ╚═╝  ╚═╝ ╚═╝  ╚═╝   ╚═══╝   ╚═╝ ╚══════╝
</pre>

[![CI](https://github.com/shepardxia/Clarvis/actions/workflows/test.yml/badge.svg)](https://github.com/shepardxia/Clarvis/actions/workflows/test.yml)
[![codecov](https://codecov.io/gh/shepardxia/Clarvis/graph/badge.svg)](https://codecov.io/gh/shepardxia/Clarvis)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

</div>

```
╭─────────╮
│  ·   ·  │  Hi! I'm Clarvis.
│    ◡    │  I live in the corner of your screen and show you
│ ·  ·  · │  what Claude is up to while it thinks and works.
╰─────────╯
```

I blink when I'm idle, look focused when I'm thinking, and sometimes you'll see rain or snow falling around me — that's the real weather outside!

## What I Can Do

- **Show my mood** — I look different when idle, thinking, running tools, or waiting for you
- **Live on your desktop** — I'm a tiny macOS widget that stays out of your way
- **Know the weather** — Rain and snow particles fall based on actual conditions outside
- **Control your Sonos** — Ask Claude to play music, and I'll make it happen

## Get Me Running

Clarvis lives in a monorepo with sibling dependencies. Clone all repos into the same parent directory:

```bash
mkdir clarvis-suite && cd clarvis-suite
git clone git@github.com:shepardxia/Clarvis.git
git clone git@github.com:shepardxia/clautify.git SpotAPI
git clone git@github.com:shepardxia/hey-buddy.git
```

Then run the setup script:

```bash
cd Clarvis
./scripts/setup.sh
```

Requires [uv](https://github.com/astral-sh/uv) and [Claude Code](https://claude.ai/code).

Then restart Claude Code and launch me:

```bash
clarvis start         # Start daemon + widget
clarvis status        # Check what's running
clarvis restart       # Stop, rebuild widget if needed, start
clarvis logs          # Tail daemon logs
```

Want me to know your exact location? `brew install corelocationcli`

## Architecture

### Rendering Pipeline

My face is rendered using a high-performance ASCII engine with aggressive caching:

```
Status Change
     |
     v
+--------------+     +---------------+     +--------------+     +---------------+
| State Cache  | --> | Pre-computed  | --> |    Layer     | --> |  Grid Wire    |
| (per status) |     |   Matrices    |     | Compositing  |     | (rows+colors) |
+--------------+     +---------------+     +--------------+     +---------------+
     |                      |                     |                     |
     v                      v                     v                     v
 0.2us switch         0.05ms render         NumPy arrays          Unix Socket
```

- **State-based caching** — All 358 animation frames pre-computed at startup (~77KB)
- **Instant status switches** — Cached matrices mean 0.2μs state transitions
- **Layer compositing** — Weather, face, and progress bar on separate NumPy layers
- **Structured grid output** — Rows + per-cell color codes sent as JSON, no ANSI encoding
- **Socket streaming** — Frames push to widget via Unix socket, no polling

### Animation System

Animations are defined in declarative YAML with composable sequences:

```yaml
# clarvis/elements/animations/idle.yaml
sequences:
  blink:
    - { eyes: "half", mouth: "smile" }
    - { eyes: "closed", mouth: "smile" }
    - { eyes: "half", mouth: "smile" }
  rest:
    - happy    # ← preset expands to full frame
    - happy

frames:
  - $rest      # ← sequence reference
  - $blink
  - $rest
```

**Shorthand system** — Write `eyes: "sparkle"` instead of `eyes: "✧"`. See [Animation Design Guide](clarvis/elements/animations/README.md).

### Weather Particles

Weather uses Numba JIT-compiled batch processing:

```python
@njit(cache=True)
def _tick_physics_batch(p_x, p_y, p_vx, p_vy, ...):
    # All particles updated in single compiled call
    for i in range(n):
        p_x[i] += p_vx[i]
        p_y[i] += p_vy[i]
```

| Particles | Physics | Render |
|-----------|---------|--------|
| 50 | 0.002ms | 0.02ms |
| 100 | 0.002ms | 0.03ms |

### Performance Summary

| Component | Time | Notes |
|-----------|------|-------|
| Status switch | 0.2μs | Cached matrix swap |
| Python render + grid | 0.084ms | NumPy compositing + `.tolist()` |
| JSON serialize | 0.027ms | 3-field wire format |
| Swift GridRenderer | ~0.1ms | Run-length color batching |
| Weather tick | 0.002ms | JIT-compiled batch |
| **Total frame** | **~0.21ms** | vs 333ms budget @ 3 FPS |

**CPU usage: ~1.2 CPU sec/hour** at 3 FPS. The daemon spends most time sleeping.

### Tool-Aware Animations

The daemon maps Claude's tool calls to semantic states:

| Tools | Status | Animation |
|-------|--------|-----------|
| Read, Grep, Glob | `reading` | Eyes scan left/right |
| Write, Edit | `writing` | Sparkle borders, talking |
| Bash | `executing` | Focused dots, arrow pulse |
| Task | `thinking` | Eyes drift, pondering |
| AskUserQuestion | `awaiting` | Curious, watching |

## Project Structure

```
clarvis/
├── server.py              # MCP server entry point
├── daemon.py              # Central hub daemon
├── core/                  # State management, display loop, IPC
├── services/              # Weather, location, voice pipeline, Sonos
├── archetypes/            # Face, weather, progress renderers
│   ├── face.py            # State-cached face animations
│   ├── weather.py         # JIT-compiled particle system
│   └── progress.py        # Percentage-cached progress bar
├── elements/              # Declarative YAML definitions
│   └── animations/        # Status animations + shorthands
├── widget/                # Render pipeline, socket server
└── ClarvisWidget/         # Native Cocoa widget (Swift)
    └── main.swift         # GridRenderer, socket client, ASR
```

## Credits

- Thinking feed adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by [@bporterfield](https://github.com/bporterfield)
- Token usage API discovery via [codelynx.dev](https://codelynx.dev/posts/claude-code-usage-limits-statusline)

## License

MIT — see [LICENSE](LICENSE)
