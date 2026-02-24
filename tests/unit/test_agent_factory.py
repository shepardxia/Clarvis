"""Verify factory creates correct backend based on config."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from clarvis.channels.agent_factory import _create_backend, _get_backend_type
from clarvis.core.agent import SessionProfile


def _make_profile(**overrides) -> SessionProfile:
    defaults = dict(
        project_dir=Path("/tmp/test"),
        session_id_path=Path("/tmp/test/session_id"),
        allowed_tools=["mcp__clarvis__*"],
        mcp_port=7778,
    )
    defaults.update(overrides)
    return SessionProfile(**defaults)


def test_get_backend_type_defaults_to_claude_code():
    """Without config, defaults to claude-code."""
    with patch(
        "clarvis.widget.config.get_config",
        side_effect=Exception("no config"),
    ):
        assert _get_backend_type() == "claude-code"


def test_get_backend_type_reads_config():
    """Reads agent_backend from config when available."""
    mock_cfg = MagicMock()
    mock_cfg.channels.agent_backend = "pi"
    with patch(
        "clarvis.widget.config.get_config",
        return_value=mock_cfg,
    ):
        assert _get_backend_type() == "pi"


def test_create_backend_claude_code():
    """claude-code backend type creates ClaudeCodeBackend."""
    profile = _make_profile()
    backend = _create_backend(profile=profile, backend_type="claude-code")
    assert backend.__class__.__name__ == "ClaudeCodeBackend"


def test_create_backend_pi():
    """pi backend type creates PiBackend."""
    profile = _make_profile()
    backend = _create_backend(profile=profile, backend_type="pi")
    assert backend.__class__.__name__ == "PiBackend"


def test_create_backend_unknown_defaults_to_claude_code():
    """Unknown backend type falls through to ClaudeCodeBackend."""
    profile = _make_profile()
    backend = _create_backend(profile=profile, backend_type="unknown-thing")
    assert backend.__class__.__name__ == "ClaudeCodeBackend"
