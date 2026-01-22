# Clarvis

```
╭─────────╮
│  ·   ·  │  Hi! I'm Clarvis—your little window into what Claude is up to.
│    ◡    │  I sit in the corner of your screen showing status, weather,
│ ·  ·  · │  and animations while Claude thinks and works.
╰─────────╯
```

## Features

- **MCP Server** — Weather, time, and session monitoring tools for Claude Code
- **Desktop Widget** — Animated ASCII avatar with weather effects (macOS)
- **Status Display** — See when Claude is idle, thinking, running tools, or waiting

```
IDLE            THINKING         RUNNING          AWAITING
╭─────────╮     ╭~~~~~~~~~╮     ╭═════════╮     ╭⋯⋯⋯⋯⋯⋯⋯⋯⋯╮
│  ·   ·  │     │  ˘   ˘  │     │  ●   ●  │     │  ?   ?  │
│    ◡    │     │    ~    │     │    ◡    │     │    ·    │
│ ·  ·  · │     │ • ◦ • ◦ │     │ • ● • ● │     │ · · · · │
╰─────────╯     ╰~~~~~~~~~╯     ╰═════════╯     ╰⋯⋯⋯⋯⋯⋯⋯⋯⋯╯
```

## Setup

```bash
./scripts/setup.sh
# Restart Claude Code, then:
cd widget && ./restart.sh
```

**Optional GPS location:** `brew install corelocationcli && CoreLocationCLI -j`

## Credits

- **Thinking Feed** adapted from [watch-claude-think](https://github.com/bporterfield/watch-claude-think) by [@bporterfield](https://github.com/bporterfield)

## License

MIT License — see [LICENSE](LICENSE)
