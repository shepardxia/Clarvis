"""Vendor patches for memu-py 1.4.0 SQLite backend.

Fixes three known bugs:
1. ``list[float]`` type mapping — SQLModel can't auto-map ``embedding`` fields.
   Fix: patch ``get_sqlalchemy_type`` to return ``JSON`` for list types.
2. ``resource_id`` required but not provided — ``create_item()`` requires a
   ``resource_id`` str, but ``create_memory_item()`` never passes one.
   Fix: make it default to ``None``.
3. Reserved table names — ``sqlite_*`` prefix is reserved by SQLite.
   Fix: rename to ``memu_*``.

Usage::

    from memu.app.service import MemoryService  # must import first
    from clarvis.vendor.memu_sqlite import apply_patch
    apply_patch()  # call before MemoryService(..., provider="sqlite")
"""

from clarvis.vendor.memu_sqlite.patches import apply_patch

__all__ = ["apply_patch"]
