"""Shared application context — passed to services for dependency discovery."""

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..display.config import ClarvisConfig
    from .signals import SignalBus
    from .state import StateStore


@dataclass(frozen=True)
class AppContext:
    """Immutable bag of core infrastructure shared across services.

    Created once in ``CentralHubDaemon.run()`` after the event loop, bus,
    and state store are ready.  Passed to service constructors so they can
    self-subscribe to signals without coupling to the daemon.
    """

    loop: asyncio.AbstractEventLoop
    bus: "SignalBus"
    state: "StateStore"
    config: "ClarvisConfig"
    memory: Any = field(default=None)
