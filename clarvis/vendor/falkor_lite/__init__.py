"""Vendored FalkorDB Lite driver for Graphiti.

Based on graphiti PR #1250 (getzep/graphiti). Provides an embedded FalkorDB
driver that uses a local file path instead of a host/port connection — no
external FalkorDB or Redis server required.

The ``falkordblite`` package bundles Redis + FalkorDB into a managed
subprocess with file-based persistence.
"""

from clarvis.vendor.falkor_lite.driver import FalkorLiteDriver

__all__ = ["FalkorLiteDriver"]
