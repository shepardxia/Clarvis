"""Agent factory -- creates Clarvis and Factoria agents."""

import logging
import shutil
from pathlib import Path

from ..core.paths import agent_home

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DATA_AGENTS_DIR = _DATA_DIR / "agents"
_DATA_GROUNDING_DIR = _DATA_DIR / "grounding"


def _scaffold_claude_md(home: Path, agent_name: str) -> None:
    """Copy bundled CLAUDE.md template to agent project dir if missing."""
    dest = home / "CLAUDE.md"
    if dest.exists():
        return
    src = _DATA_AGENTS_DIR / agent_name / "CLAUDE.md"
    if src.exists():
        home.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)


def _scaffold_grounding(home: Path, agent_name: str) -> None:
    """Copy bundled grounding files to agent project dir if missing."""
    src_dir = _DATA_GROUNDING_DIR / agent_name
    if not src_dir.is_dir():
        return
    dest_dir = home / "grounding"
    for src_file in sorted(src_dir.iterdir()):
        if not src_file.is_file():
            continue
        dest_file = dest_dir / src_file.name
        if not dest_file.exists():
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dest_file)


def _create_agent(
    session_key: str,
    project_dir: Path,
    model: str | None = None,
    max_thinking_tokens: int | None = None,
):
    """Shared agent construction: config -> Agent -> ensure_project_dir."""
    from .agent import Agent, AgentConfig

    config = AgentConfig(
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
    """Create the Clarvis agent (voice + terminal) at ~/.clarvis/clarvis/."""
    clarvis_home = agent_home("clarvis")
    agent = _create_agent("clarvis", clarvis_home, model, max_thinking_tokens)
    _scaffold_claude_md(clarvis_home, "clarvis")
    return agent


def create_factoria_agent(
    model: str | None = None,
    max_thinking_tokens: int | None = None,
):
    """Create the Factoria agent (online channels) at ~/.clarvis/factoria/."""
    channels_dir = agent_home("factoria")
    agent = _create_agent("factoria", channels_dir, model, max_thinking_tokens)
    _scaffold_claude_md(channels_dir, "factoria")
    _scaffold_grounding(channels_dir, "factoria")
    return agent
