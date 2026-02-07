"""General-purpose clickable region system for the widget grid.

Daemon registers named regions with handlers. Regions are pushed to the
widget via ``set_click_regions`` command for hover cursor feedback.
The widget hit-tests on click and sends ``region_click`` with the region id.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from clarvis.widget.socket_server import WidgetSocketServer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClickRegion:
    """A rectangular clickable area in the grid."""

    id: str
    row: int
    col: int
    width: int
    height: int


class ClickRegionManager:
    """Manages clickable grid regions and dispatches clicks to handlers."""

    def __init__(self, socket_server: WidgetSocketServer) -> None:
        self._regions: dict[str, ClickRegion] = {}
        self._handlers: dict[str, Callable[[], None]] = {}
        self._socket = socket_server

    def register(self, region: ClickRegion, handler: Callable[[], None]) -> None:
        """Register a clickable region with its click handler."""
        self._regions[region.id] = region
        self._handlers[region.id] = handler
        self.push_regions()

    def unregister(self, region_id: str) -> None:
        """Remove a region and its handler."""
        self._regions.pop(region_id, None)
        self._handlers.pop(region_id, None)
        self.push_regions()

    def handle_click(self, region_id: str) -> None:
        """Dispatch a click to the registered handler for *region_id*."""
        handler = self._handlers.get(region_id)
        if handler:
            logger.info("Click on region %r", region_id)
            handler()
        else:
            logger.debug("Click on unknown region %r", region_id)

    def push_regions(self) -> None:
        """Push current regions to widget (call on widget connect too)."""
        regions_list = [asdict(r) for r in self._regions.values()]
        self._socket.send_command({
            "method": "set_click_regions",
            "params": {"regions": regions_list},
        })
