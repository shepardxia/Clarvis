"""Load .env file into os.environ early in startup."""

import os
from pathlib import Path

# Clarvis project root: …/Clarvis/
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv() -> None:
    """Load .env from the Clarvis project root into os.environ.

    Only sets variables not already present in the environment
    (existing env vars take precedence). Skips blank lines and comments.
    """
    dotenv = _PROJECT_ROOT / ".env"
    if not dotenv.exists():
        return
    for line in dotenv.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())
