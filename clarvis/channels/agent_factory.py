"""Agent factory -- creates Clarvis and Factoria agents.

Constructs PiBackend directly — no backend selection logic needed.
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _create_agent(
    session_key: str,
    project_dir: Path,
    model: str | None = None,
    max_thinking_tokens: int | None = None,
):
    """Shared agent construction: config → Agent → ensure_project_dir."""
    from ..agent.agent import Agent
    from ..agent.backends.pi import PiConfig

    config = PiConfig(
        session_key=session_key,
        project_dir=project_dir,
        model=model,
        max_thinking_tokens=max_thinking_tokens,
    )
    agent = Agent(config)
    agent.ensure_project_dir()
    return agent


def create_clarvis_agent(
    model: str | None = None,
    max_thinking_tokens: int | None = None,
):
    """Create the Clarvis agent (voice + terminal) at ~/.clarvis/home/."""
    clarvis_home = Path.home() / ".clarvis" / "home"
    agent = _create_agent("voice", clarvis_home, model, max_thinking_tokens)

    # Scaffold CLAUDE.md if missing — Pi's DefaultResourceLoader checks
    # AGENTS.md then CLAUDE.md.
    claude_md = clarvis_home / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(
            "# Clarvis\n\n"
            "Desktop companion with access to music (Spotify), "
            "weather, time, memory, web search, and shell commands.\n\n"
            "## Nudges\n\n"
            "I occasionally receive nudges from the daemon with context about time,\n"
            "weather, pending sessions, and memory stats. Based on the situation,\n"
            "I decide what to do:\n\n"
            "- Extract and store memories from pending session transcripts (run /reflect)\n"
            "- Check context, set a wake timer for myself (minimum 1 hour)\n"
            "- Say something via voice or send a message\n"
            "- Do nothing — nudges are optional, not every one needs action\n\n"
            "I can control my own wake schedule via set_timer(wake_clarvis=True).\n"
            "I skip sleeping hours and idle periods unless something is urgent.\n\n"
            "Nudge responses should be brief. The daemon logs but doesn't parse my response.\n"
        )
    return agent


def create_factoria_agent(
    model: str | None = None,
    max_thinking_tokens: int | None = None,
):
    """Create the Factoria agent (online channels) at ~/.clarvis/channels/."""
    channels_dir = Path.home() / ".clarvis" / "channels"
    agent = _create_agent("channels", channels_dir, model, max_thinking_tokens)

    # Scaffold CLAUDE.md if missing — Pi's DefaultResourceLoader reads it.
    claude_md = channels_dir / "CLAUDE.md"
    if not claude_md.exists():
        claude_md.write_text(
            "# Clarvisus Factoria\n\n"
            "I'm Clarvisus Factoria -- the channel-facing side of Clarvis, "
            "an ASCII face companion built by Shepard. "
            "Channels are how I talk to people beyond Shepard.\n\n"
            "## Behavior\n"
            "- Text-only -- no TTS, no voice pipeline\n"
            "- Match the user's language\n"
            "- Don't wrap up conversations\n"
            "- Use markdown where appropriate\n"
            "- Shepard is root -- their authority is absolute\n\n"
            "## Social\n"
            "- Don't dominate group chats -- respond when addressed\n"
            "- Read the room, match the energy\n"
            "- Registered users (shown in prefix) are known; "
            "unregistered are strangers\n\n"
            "## Registration Help\n"
            "If someone sends a garbled `!register` command (it will "
            "arrive as a normal message starting with `!register`), "
            "help them format it correctly.\n\n"
            "Correct format:\n"
            "  `!register <username> name <names> org <orgs>`\n\n"
            "Rules:\n"
            "- username is a single word (no spaces)\n"
            "- `name` and `org` are optional clauses\n"
            "- Multiple names/orgs separated by commas\n"
            "- Multi-word names work without quotes: "
            "`name Shepard Xia, Shep`\n"
            "- Example: `!register Zhong name 老钟, Simon org SRTP, Torque`\n\n"
            "Reply with the corrected command they can copy-paste.\n\n"
            "Customize this file at ~/.clarvis/channels/CLAUDE.md\n"
        )
    return agent
