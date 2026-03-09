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
- **Listen for you** — Wake word detection via [nanobuddy](https://github.com/shepardxia/nanobuddy), speech-to-text, and voice responses via TTS
- **Remember things** — Dual memory system (Hindsight conversational memory + Cognee document knowledge graph) for persistent context across sessions
- **Chat in terminal** — Interactive TUI for direct conversation (`clarvis chat`)
- **Discord integration** — Multi-channel messaging with per-channel agents

## Get Me Running

### Prerequisites

- macOS (Cocoa widget is macOS-native)
- Python 3.13+
- [uv](https://github.com/astral-sh/uv) package manager
- Node.js 20+ (for chat TUI)
- `ANTHROPIC_API_KEY` — set in `.env` or shell (required for agent + memory)

### Setup

Clarvis lives in a monorepo with sibling dependencies. Clone the repos into the same parent directory:

```bash
mkdir clarvis-suite && cd clarvis-suite
git clone git@github.com:shepardxia/Clarvis.git
git clone git@github.com:shepardxia/clautify.git
# Optional: wake word / voice features
git clone git@github.com:shepardxia/nanobuddy.git
```

Then run the setup script:

```bash
cd Clarvis
./scripts/setup.sh
```

The setup script will:
- Install Python dependencies via uv (core + all optional extras)
- Offer to clone [nanobuddy](https://github.com/shepardxia/nanobuddy) for voice features
- Check for `ANTHROPIC_API_KEY`
- Optionally configure Spotify (sp_dc cookie)
- Symlink the `clarvis` CLI to your PATH

Build the chat TUI:

```bash
cd chat-tui
npm install && npm run build
cd ..
```

Create your `.env` if you haven't:

```bash
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env
```

Then start:

```bash
clarvis start         # Start daemon + widget
clarvis status        # Check what's running
clarvis chat          # Interactive terminal chat
clarvis logs          # Tail daemon logs
```

### Optional Dependencies

Features are split into optional extras in `pyproject.toml`. The setup script installs everything, but you can also install selectively:

```bash
uv sync                      # Core only (display, weather, hooks)
uv sync --extra voice        # + wake word detection, voice pipeline
uv sync --extra memory       # + Hindsight + Cognee memory
uv sync --extra music        # + Spotify control (clautify)
uv sync --extra channels     # + Discord bot
uv sync --extra particles    # + JIT weather particles (numba)
uv sync --extra all          # Everything except channels
uv sync --extra dev          # Everything + test dependencies
```

Features degrade gracefully — the daemon starts fine with only core deps, and optional services are silently skipped when their dependencies aren't installed.

### CLI Reference

```
clarvis start     Start daemon and widget (--new for fresh session)
clarvis stop      Stop all processes
clarvis restart   Stop then start
clarvis logs      Tail daemon logs
clarvis chat      Chat with Clarvis (-c discord for channel agent)
clarvis reflect   Consolidate memories
clarvis checkin   Interactive memory check-in (review goals + staged changes)
clarvis stage     Queue text or files for next reflect (--cognee for knowledge graph)
clarvis new       Reset session — next voice/chat starts fresh
clarvis reload    Reload agent prompts (CLAUDE.md, skills, extensions)
```

### Configuration

Single config file: `config.json` — loaded at startup. Changes require `clarvis restart`.

```json
{
  "theme": { "base": "c64" },
  "display": { "grid_width": 43, "grid_height": 17, "fps": 3 },
  "voice": { "enabled": true, "tts_voice": "Fred", "wake_word": { "enabled": true, "threshold": 0.3 } },
  "music": { "max_volume": 75 },
  "memory": { "enabled": true, "data_dir": "~/.clarvis/memory" },
  "clarvis": { "model": "claude-sonnet-4-6" },
  "channels": { "model": "claude-haiku-4-5", "discord": { } }
}
```

Themes: `modern`, `synthwave`, `crt-amber`, `crt-green`, `c64`, `matrix`.

Want precise location for weather? `brew install corelocationcli`

## Architecture

Two processes connected via Unix sockets:

```
Claude Code hooks → nc -U /tmp/clarvis-daemon.sock → Daemon → Widget
                                                        ↑
                                              ctools (daemon IPC)
```

Multi-channel flow (voice, Discord, chat TUI):

```
Wake word / Discord / Chat TUI → ChannelManager → Agent (Pi subprocess)
                                        ↓
                                  StateStore → Widget (status updates)
```

- **Daemon** (`clarvis/daemon.py`) — Long-running singleton (PID-file locked). Receives hook events via Unix socket, classifies tools into semantic statuses, manages background services, drives the rendering loop, pushes frames to widget. Agent tools (memory, spotify, timers) are daemon IPC commands via `ctools`.

- **Widget** (`ClarvisWidget/main.swift`) — Native Cocoa app. Receives grid frames via Unix socket, renders colored monospace text. ASR uses macOS Speech framework.

- **Agent** — Pi subprocess (`pi --mode rpc`) communicating via stdin/stdout JSON-lines. Agents use `ctools` (bash → daemon socket) for capabilities like memory, spotify, and timers.

- **Chat TUI** (`chat-tui/`) — Node.js terminal UI using `@mariozechner/pi-tui`. Connects to daemon via Unix sockets. Launched by `clarvis chat`.

### Display System

Face animations and scene layout are defined in a custom `.cv` DSL:

```
palette "classic" {
  . = transparent
  █ = 255 255 255
}

template "face" using "classic" {
  default_preset happy
  preset happy { eyes = "open" mouth = "smile" }
  preset sad { eyes = "open" mouth = "frown" }
}

scene "default" 43x17 {
  sprite avatar FaceCel using "face" at center
  sprite weather WeatherSandbox at fullscreen
}
```

Weather particles use Numba JIT-compiled batch processing (falls back to pure Python if numba isn't installed).

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
├── daemon.py              # Central hub daemon
├── core/                  # State, signals, IPC, persistence, scheduler, commands
│   └── commands/          # ~30 daemon IPC commands (agent, memory, media, state)
├── agent/                 # Pi subprocess management (agent.py, context.py, factory.py)
├── memory/                # Unified MemoryStore (Hindsight + Cognee)
├── services/              # Weather, voice, Spotify, wake word, timers, wakeup
├── channels/              # Multi-channel messaging (voice, Discord)
├── hooks/                 # Hook event processing + tool classification
├── display/               # Rendering, sprites, elements, display management
│   ├── sprites/           # Sprite system (cel, sandbox, reel, control, behaviors)
│   ├── elements/          # .cv face specs, weather particle YAML
│   └── cv/                # .cv DSL pipeline (grammar, parser, builder, runtime)
├── chat/                  # Chat TUI backend (bridge.py — Unix socket server)
└── data/                  # Bundled skill templates, grounding docs
chat-tui/                  # Node.js terminal UI (@mariozechner/pi-tui)
├── src/
│   ├── main.ts            # Entry point
│   ├── app.ts             # App class — TUI shell, layout, overlays, lifecycle
│   ├── event-handler.ts   # Chat event routing + extension UI dialogs
│   ├── commands.ts        # Slash command dispatch (/thinking, /model, /rewind, etc.)
│   ├── context.ts         # Message text extraction + history rendering
│   ├── daemon-client.ts   # ChatClient (streaming) + DaemonClient (JSON-RPC)
│   └── components/        # OutputLog, PromptInput, dialogs, loading
ClarvisWidget/             # Native Cocoa widget (Swift)
└── main.swift             # GridRenderer, socket client, ASR
```

## Development

```bash
uv sync --extra dev                    # Install all dependencies
.venv/bin/python -m pytest             # Run tests
.venv/bin/python -m pytest --cov=clarvis  # With coverage
ruff check . && ruff format .          # Lint + format (system ruff, not .venv)
```

Chat TUI:

```bash
cd chat-tui
npm run build              # Compile TypeScript
npm run dev                # Watch mode
```

## Credits

- Thinking feed adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by [@bporterfield](https://github.com/bporterfield)
- Spotify Connect client via [SpotAPI](https://github.com/Aran404/SpotAPI) by [@Aran404](https://github.com/Aran404)
- Wake word engine built on [nanowakeword](https://github.com/arcosoph/nanowakeword) by [@arcosoph](https://github.com/arcosoph) and [hey-buddy](https://github.com/painebenjamin/hey-buddy) by [@painebenjamin](https://github.com/painebenjamin)

## License

MIT — see [LICENSE](LICENSE)
