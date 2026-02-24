"""Centralized logging configuration for Clarvis daemon.

Call setup_logging() once at startup (in daemon.main()) to configure:
- RotatingFileHandler → logs/daemon.log (timestamped, single source of truth)
- Noisy third-party loggers suppressed to WARNING
- sys.excepthook → routes unhandled exceptions through logging
- sys.stderr → redirected to logging (captures C extension output etc.)

Everything goes to daemon.log — no separate err.log needed.
"""

import logging
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

# Third-party loggers that spam at INFO level
_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "graphiti_core",
    "nanobuddy.detector",
    "onnxruntime",
    "uvicorn.access",
)

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


class _StderrToLogger:
    """File-like wrapper that routes stderr writes to a logger.

    Uses a per-thread reentrance guard to break infinite recursion:
    handler emit → stderr.write → logger.log → handler → …
    When reentrance is detected, falls back to the real stderr fd.
    """

    def __init__(self, logger: logging.Logger, level: int = logging.WARNING):
        self._logger = logger
        self._level = level
        self._guard = threading.local()

    def write(self, msg: str) -> int:
        if not msg or not msg.strip():
            return len(msg)
        # Break recursion: if we're already inside a write(), fall back to raw stderr
        if getattr(self._guard, "active", False):
            sys.__stderr__.write(msg)
            return len(msg)
        self._guard.active = True
        try:
            for line in msg.rstrip().splitlines():
                self._logger.log(self._level, "%s", line)
        finally:
            self._guard.active = False
        return len(msg)

    def flush(self) -> None:
        pass

    def fileno(self) -> int:
        # Some libraries (e.g. subprocess) need a real fd — fall back to original stderr
        return sys.__stderr__.fileno()


def setup_logging(log_dir: Path) -> None:
    """Configure root logger with file rotation and stderr capture.

    All structured logs and unhandled exceptions go to daemon.log.
    No separate err.log is needed.

    Args:
        log_dir: Directory for log files (created if missing).
    """
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    # Rotating file handler — 500 KB, keep 2 backups
    file_handler = RotatingFileHandler(
        log_dir / "daemon.log",
        maxBytes=512_000,
        backupCount=2,
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)

    # Suppress noisy third-party loggers
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)

    # Route unhandled exceptions through logging instead of raw stderr
    _logger = logging.getLogger("clarvis.crash")

    def _excepthook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))

    sys.excepthook = _excepthook

    # Redirect stderr writes (e.g. from C extensions, subprocess) to logging
    sys.stderr = _StderrToLogger(logging.getLogger("clarvis.stderr"))
