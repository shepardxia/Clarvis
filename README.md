# Clarvis

```
╭─────────╮
│  ·   ·  │  Hi! I'm Clarvis—your little window into what Claude is up to.
│    ◡    │  I sit in the corner of your screen showing status, weather,
│ ·  ·  · │  and animations while Claude thinks and works.
╰─────────╯
```

## Features

- **MCP Server** — Weather, time, Sonos control, and session monitoring tools for Claude Code
- **Desktop Widget** — Native macOS Swift widget with animated ASCII avatar and weather particles
- **Weather Effects** — Dynamic intensity based on wind speed, precipitation, and snowfall
- **Status Display** — See when Claude is idle, thinking, running tools, or waiting
- **Sonos Control** — Play music, adjust volume, manage queues via MCP tools

## Setup

```bash
./scripts/setup.sh
# Restart Claude Code to enable MCP server
```

**Run the widget:**
```bash
./ClarvisWidget/ClarvisWidget &
```

**Optional GPS location:** `brew install corelocationcli`

## Architecture

```
central_hub/
├── server.py          # MCP server entry point
├── core/              # Hub data, cache, time utilities
├── services/          # Weather, location, Sonos, thinking feed
└── widget/            # ASCII renderer, display service
```

## Credits

- **Thinking Feed** adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by [@bporterfield](https://github.com/bporterfield)

## License

MIT License — see [LICENSE](LICENSE)
