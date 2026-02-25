"""Shared test fixtures."""

import pytest

from clarvis.core.state import StateStore
from clarvis.services.session_tracker import SessionTracker


@pytest.fixture
def state():
    return StateStore()


@pytest.fixture
def session_tracker(state):
    return SessionTracker(state)
