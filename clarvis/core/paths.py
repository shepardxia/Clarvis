from pathlib import Path

CLARVIS_HOME = Path.home() / ".clarvis"
STAGING_DIR = CLARVIS_HOME / "staging"
STAGING_INBOX = STAGING_DIR / "inbox"
STAGING_DIGESTED = STAGING_DIR / "digested"


def agent_home(name: str) -> Path:
    """Canonical agent project directory: ~/.clarvis/{name}/"""
    return CLARVIS_HOME / name
