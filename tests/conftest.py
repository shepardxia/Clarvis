"""Shared test fixtures."""

import pytest

from clarvis.core.session_tracker import SessionTracker
from clarvis.core.state import StateStore


@pytest.fixture
def state():
    """Fresh StateStore instance (no global singleton)."""
    return StateStore()


@pytest.fixture
def session_tracker(state):
    """SessionTracker backed by a fresh StateStore."""
    return SessionTracker(state)
