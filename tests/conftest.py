"""Shared test fixtures."""

import pytest

from clarvis.core.session_tracker import SessionTracker
from clarvis.core.state import StateStore


@pytest.fixture
def state():
    return StateStore()


@pytest.fixture
def session_tracker(state):
    return SessionTracker(state)
