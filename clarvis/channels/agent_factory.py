"""Agent factory -- creates master and channel agents.

Extracted from daemon.py to centralize agent construction logic.
Reads ``channels.agent_backend`` from config to decide which backend
(``claude-code`` or ``pi``) to construct and passes it to ``Agent``.
"""

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_backend_type() -> str:
    """Read agent_backend from config, defaulting to 'claude-code'."""
    try:
        from ..display.config import get_config

        cfg = get_config()
        return cfg.channels.agent_backend
    except Exception:
        return "claude-code"


def _create_backend(
    profile,  # SessionProfile
    backend_type: str,
    model: str | None = None,
    max_thinking_tokens: int | None = None,
    force_new: bool = False,
    system_prompt: str | None = None,
):
    """Create the appropriate backend based on config.

    Returns:
        An ``AgentBackend``-compatible instance.
    """
    from ..agent.backends.protocol import BackendConfig

    config = BackendConfig(
        session_key=profile.project_dir.name,  # "home" or "channels"
        project_dir=profile.project_dir,
        session_id_path=profile.session_id_path,
        system_prompt=system_prompt,
        model=model,
        max_thinking_tokens=max_thinking_tokens,
        mcp_port=profile.mcp_port,
        allowed_tools=profile.allowed_tools,
    )

    if backend_type == "pi":
        from ..agent.backends.pi import PiBackend

        return PiBackend(config)
    else:
        from ..agent.backends.claude_code import ClaudeCodeBackend

        return ClaudeCodeBackend(config, force_new=force_new)


def _create_agent(
    session_key: str,
    project_dir: Path,
    mcp_port: int,
    event_loop: asyncio.AbstractEventLoop,
    model: str | None = None,
    max_thinking_tokens: int | None = None,
    force_new: bool = False,
):
    """Shared agent construction: profile → backend → Agent → ensure_project_dir."""
    from ..agent.agent import VOICE_ALLOWED_TOOLS, Agent, SessionProfile

    profile = SessionProfile(
        project_dir=project_dir,
        session_id_path=project_dir / "session_id",
        allowed_tools=VOICE_ALLOWED_TOOLS,
        mcp_port=mcp_port,
    )
    backend = _create_backend(
        profile=profile,
        backend_type=_get_backend_type(),
        model=model,
        max_thinking_tokens=max_thinking_tokens,
        force_new=force_new,
    )
    agent = Agent(
        session_key=session_key,
        profile=profile,
        event_loop=event_loop,
        backend=backend,
        force_new=force_new,
    )
    agent.ensure_project_dir()
    return agent


def create_clarvis_agent(
    event_loop: asyncio.AbstractEventLoop,
    model: str | None = None,
    max_thinking_tokens: int | None = None,
    force_new: bool = False,
    mcp_port: int = 7778,
):
    """Create the Clarvis agent (voice + terminal) at ~/.clarvis/home/."""
    clarvis_home = Path.home() / ".clarvis" / "home"
    agent = _create_agent("voice", clarvis_home, mcp_port, event_loop, model, max_thinking_tokens, force_new)

    # Scaffold CLAUDE.md if missing — both Claude Code and Pi read it
    # (Pi's DefaultResourceLoader checks AGENTS.md then CLAUDE.md).
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
    event_loop: asyncio.AbstractEventLoop,
    model: str | None = None,
    max_thinking_tokens: int | None = None,
    force_new: bool = False,
    mcp_port: int = 7779,
):
    """Create the Factoria agent (online channels) at ~/.clarvis/channels/."""
    channels_dir = Path.home() / ".clarvis" / "channels"
    agent = _create_agent("channels", channels_dir, mcp_port, event_loop, model, max_thinking_tokens, force_new)

    # Scaffold CLAUDE.md if missing — both Claude Code and Pi read it.
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
