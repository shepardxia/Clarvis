"""Atomic JSON file persistence utilities."""

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def json_save_atomic(path: Path, data: Any) -> bool:
    """Atomically save *data* as JSON via tmp-file + rename.

    Creates parent directories if needed.  Returns ``True`` on success.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)
        return True
    except OSError:
        logger.warning("Failed to save %s", path, exc_info=True)
        return False


def json_load_safe(path: Path) -> Any | None:
    """Load JSON from *path*, returning ``None`` on missing/corrupt files."""
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return None
