"""Behavior plugins for sprite movement and animation control."""

from abc import ABC, abstractmethod


class Behavior(ABC):
    """Base class for sprite behaviors (movement, animation triggers)."""

    @abstractmethod
    def update(self, sprite, scene) -> None: ...


class StaticBehavior(Behavior):
    """No-op behavior — sprite stays put."""

    def update(self, sprite, scene) -> None:
        pass


class DriftBehavior(Behavior):
    """Slow linear drift in a direction. Phase 2+."""

    def update(self, sprite, scene) -> None:
        raise NotImplementedError


class WanderBehavior(Behavior):
    """Random walk within bounds. Phase 2+."""

    def update(self, sprite, scene) -> None:
        raise NotImplementedError


class PatrolBehavior(Behavior):
    """Back-and-forth along a path. Phase 2+."""

    def update(self, sprite, scene) -> None:
        raise NotImplementedError
