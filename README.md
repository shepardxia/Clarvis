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
- **Control your music** — Spotify playback via [clautify](https://github.com/shepardxia/clautify) DSL (`play "jazz" volume 70 mode shuffle`)
- **Listen for you** — Wake word detection via [hey-buddy](https://github.com/shepardxia/hey-buddy), speech-to-text, and voice responses via TTS
- **Track token usage** — Monitor Claude API consumption (5-hour and 7-day limits)

## Get Me Running

Clarvis lives in a monorepo with sibling dependencies. Clone all repos into the same parent directory:

```bash
mkdir clarvis-suite && cd clarvis-suite
git clone git@github.com:shepardxia/Clarvis.git
git clone git@github.com:shepardxia/clautify.git
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

Three processes connected via Unix sockets:

```
Claude Code hooks → nc -U /tmp/clarvis-daemon.sock → Daemon → Widget
                                                        ↑
                                             MCP Server (tools)
```

- **MCP Server** — Thin client registered with Claude Code. Exposes tools for weather, status, music control, thinking feed, and token usage. Communicates with daemon via JSON-RPC.
- **Daemon** — Long-running singleton. Receives hook events, classifies tools into semantic statuses, manages background services (weather, location, voice, Spotify), drives the rendering loop, and pushes structured grid frames to the widget.
- **Widget** — Native Cocoa app. Receives grid data (rows, cell colors, theme color) via Unix socket, renders colored monospace text. Supports click regions for interactive elements like the mic toggle.

### Rendering Pipeline

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
- **Instant status switches** — Cached matrices mean 0.2us state transitions
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
    - happy    # preset expands to full frame
    - happy

frames:
  - $rest      # sequence reference
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

### Resource Usage

| Metric | Value |
|--------|-------|
| CPU | ~1.2 CPU sec/hour |
| Memory | ~45 MB resident |
| Frame budget | <0.3ms of 200ms (5 FPS) |
| Grid size | 29×12 cells |
| Staleness timeout | 30s |
| Startup | ~2s |

### Tool-Aware Animations

The daemon maps Claude's tool calls to semantic states:

| Tools | Status | Animation |
|-------|--------|-----------|
| Read, Grep, Glob | `reading` | Eyes scan left/right |
| Write, Edit | `writing` | Sparkle borders, talking |
| Bash | `executing` | Focused dots, arrow pulse |
| Task | `thinking` | Eyes drift, pondering |
| AskUserQuestion | `awaiting` | Curious, watching |

MCP tools use heuristic keyword matching on the tool name suffix.

## Project Structure

```
clarvis/
├── server.py              # MCP server (FastMCP 2.x)
├── daemon.py              # Central hub daemon
├── spotify_tools.py       # Spotify DSL tool (mounted sub-server)
├── core/                  # State management, display loop, IPC, scheduler
├── services/              # Weather, location, voice pipeline, Spotify, token usage
├── archetypes/            # Face, weather, progress renderers
│   ├── face.py            # State-cached face animations
│   ├── weather.py         # JIT-compiled particle system
│   └── progress.py        # Percentage-cached progress bar
├── elements/              # Declarative YAML definitions
│   └── animations/        # Status animations + shorthands
├── widget/                # Render pipeline, socket server, click regions
└── ClarvisWidget/         # Native Cocoa widget (Swift)
    └── main.swift         # GridRenderer, socket client, ASR
```

## Development

```bash
uv sync --extra dev                    # Install all dependencies
uv run pytest                          # Run tests (69 tests, ~3s)
uv run pytest --cov=clarvis            # With coverage
uv run ruff check . && uv run ruff format .  # Lint + format
```

Pre-commit hooks run ruff lint and ruff-format on every commit.

## Credits

- Thinking feed adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by [@bporterfield](https://github.com/bporterfield)
- Token usage API discovery via [codelynx.dev](https://codelynx.dev/posts/claude-code-usage-limits-statusline)
- Music control via [clautify](https://github.com/shepardxia/clautify) (Spotify DSL)
- Wake word detection via [hey-buddy](https://github.com/shepardxia/hey-buddy)

## License

MIT — see [LICENSE](LICENSE)
