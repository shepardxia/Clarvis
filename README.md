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

```bash
./scripts/setup.sh    # Set me up as an MCP server
```

Then restart Claude Code and launch me:

```bash
./ClarvisWidget/ClarvisWidget &
```

Want me to know your exact location? `brew install corelocationcli`

## Architecture

### Rendering Pipeline

My face is rendered using a high-performance ASCII engine with aggressive caching:

```
┌─────────────────────────────────────────────────────────────┐
│                    Frame Render Pipeline                    │
├─────────────────────────────────────────────────────────────┤
│  Status Change                                              │
│       ↓                                                     │
│  ┌─────────────┐    ┌──────────────┐    ┌───────────────┐  │
│  │ State Cache │ →  │ Pre-computed │ →  │ Layer         │  │
│  │ (per status)│    │ Matrices     │    │ Compositing   │  │
│  └─────────────┘    └──────────────┘    └───────────────┘  │
│       ↓                    ↓                    ↓          │
│  0.2μs switch       0.05ms render         Socket Push      │
└─────────────────────────────────────────────────────────────┘
```

- **State-based caching** — All 358 animation frames pre-computed at startup (~77KB)
- **Instant status switches** — Cached matrices mean 0.2μs state transitions
- **Layer compositing** — Weather, face, and progress bar on separate layers
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
| Full render | 0.06ms | Pre-computed frames |
| Weather tick | 0.002ms | JIT-compiled batch |
| **Total frame** | **~0.1ms** | vs 333ms budget @ 3 FPS |

**CPU usage: ~0.03%** for rendering. The daemon spends most time sleeping.

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
├── core/                  # State management, caching
├── services/              # Weather, location, Sonos
├── archetypes/            # Face, weather, progress renderers
│   ├── face.py            # State-cached face animations
│   ├── weather.py         # JIT-compiled particle system
│   └── progress.py        # Percentage-cached progress bar
├── elements/              # Declarative YAML definitions
│   └── animations/        # Status animations + shorthands
└── widget/                # Renderer, socket server
```

## Credits

- Thinking feed adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by [@bporterfield](https://github.com/bporterfield)
- Token usage API discovery via [codelynx.dev](https://codelynx.dev/posts/claude-code-usage-limits-statusline)

## License

MIT — see [LICENSE](LICENSE)
