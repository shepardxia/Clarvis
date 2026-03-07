from pathlib import Path

CLARVIS_HOME = Path.home() / ".clarvis"


def agent_home(name: str) -> Path:
    """Canonical agent project directory: ~/.clarvis/{name}/"""
    return CLARVIS_HOME / name
