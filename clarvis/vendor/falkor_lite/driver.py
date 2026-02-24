"""FalkorDB Lite driver — embedded FalkorDB via falkordblite.

Vendored from graphiti PR #1250 (getzep/graphiti).
Original: graphiti_core/driver/falkordb_lite_driver.py

Copyright 2024, Zep Software, Inc.
Licensed under the Apache License, Version 2.0.
"""

import logging
from typing import Any

try:
    from redislite.async_falkordb_client import (  # type: ignore[reportMissingImports]
        AsyncFalkorDB as LiteAsyncFalkorDB,
    )
except ImportError:
    raise ImportError(
        "falkordblite is required for FalkorLiteDriver. Install it with: pip install falkordblite"
    ) from None

from graphiti_core.driver.driver import GraphDriver
from graphiti_core.driver.falkordb_driver import FalkorDriver

logger = logging.getLogger(__name__)


class FalkorLiteDriver(FalkorDriver):
    """Embedded FalkorDB driver using falkordblite.

    Uses a local file path for storage instead of a host/port connection.
    No external FalkorDB or Redis server is required — falkordblite runs
    an embedded instance as a subprocess.

    All query operations, search, indexing, and graph logic are inherited
    from FalkorDriver.

    Args:
        path: File path for the embedded database storage.
        database: Name of the graph/database to use. Defaults to 'default_db'.
        falkor_db: An existing AsyncFalkorDB lite instance to reuse (for clone support).
    """

    def __init__(
        self,
        path: str,
        database: str = "default_db",
        falkor_db: Any = None,
    ):
        self._path = path
        lite_client = falkor_db if falkor_db is not None else LiteAsyncFalkorDB(path)
        # Pass the lite client to FalkorDriver via dependency injection.
        # This bypasses FalkorDriver's host/port initialization entirely.
        super().__init__(falkor_db=lite_client, database=database)

    async def close(self) -> None:
        """Close the embedded FalkorDB instance."""
        if hasattr(self.client, "aclose"):
            await self.client.aclose()  # type: ignore[reportAttributeAccessIssue]
        elif hasattr(self.client, "close"):
            await self.client.close()  # type: ignore[reportAttributeAccessIssue]

    def clone(self, database: str) -> "GraphDriver":
        """Clone with a different database, reusing the same embedded client."""
        if database == self._database:
            return self
        elif database == self.default_group_id:
            return FalkorLiteDriver(path=self._path, falkor_db=self.client)
        else:
            return FalkorLiteDriver(path=self._path, falkor_db=self.client, database=database)
