<div align="center">

<pre>
 ██████╗  ██╗       █████╗  ██████╗  ██╗   ██╗ ██╗ ███████╗
██╔════╝  ██║      ██╔══██╗ ██╔══██╗ ██║   ██║ ██║ ██╔════╝
██║       ██║      ███████║ ██████╔╝ ██║   ██║ ██║ ███████╗
██║       ██║      ██╔══██║ ██╔══██╗ ╚██╗ ██╔╝ ██║ ╚════██║
╚██████╗  ███████╗ ██║  ██║ ██║  ██║  ╚████╔╝  ██║ ███████║
 ╚═════╝  ╚══════╝ ╚═╝  ╚═╝ ╚═╝  ╚═╝   ╚═══╝   ╚═╝ ╚══════╝
</pre>

[![GitHub CI](https://github.com/shepardxia/Clarvis/actions/workflows/test.yml/badge.svg)](https://github.com/shepardxia/Clarvis/actions/workflows/test.yml)
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

I blink when I'm idle, look focused when I'm thinking, and sometimes you'll see rain or snow falling around me—that's the real weather outside!

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

## How I'm Built

```
central_hub/
├── server.py          # My MCP server entry point
├── core/              # Hub data, cache, time utilities
├── services/          # Weather, location, Sonos, thinking feed
└── widget/            # ASCII renderer, display service
```

## Credits

My thinking feed was adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by [@bporterfield](https://github.com/bporterfield)

## License

MIT — see [LICENSE](LICENSE)
