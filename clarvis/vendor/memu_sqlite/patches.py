"""Monkey-patches for memu-py 1.4.0 SQLite backend bugs."""

_PATCHED = False


def apply_patch() -> None:
    """Patch memu's SQLite backend to fix three bugs.

    1. **list[float] column mapping** — Base models define
       ``embedding: list[float] | None``. SQLModel can't auto-map this.
       Fix: patch ``get_sqlalchemy_type`` to map ``list`` → ``JSON``.

    2. **resource_id required in create_item** —
       ``SQLiteMemoryItemRepo.create_item`` requires ``resource_id: str``,
       but ``PatchMixin._patch_create_memory_item`` never passes it.
       Fix: make it default to ``None``.

    3. **Reserved table names** — Table names ``sqlite_*`` are reserved by
       SQLite itself. Fix: patch ``get_sqlite_sqlalchemy_models`` to use
       ``memu_*`` prefix instead.

    Must be called after ``memu.app.service.MemoryService`` has been imported
    (to avoid memU's internal circular import chain), but before
    ``MemoryService(provider='sqlite')`` is constructed.
    """
    global _PATCHED
    if _PATCHED:
        return

    import sqlmodel.main as _sqlmodel_main
    from sqlalchemy import JSON

    # --- Fix 1: Patch get_sqlalchemy_type to handle list[float] → JSON
    _orig_get_sqlalchemy_type = _sqlmodel_main.get_sqlalchemy_type

    def _patched_get_sqlalchemy_type(field):
        try:
            return _orig_get_sqlalchemy_type(field)
        except ValueError:
            import types

            ann = field.annotation
            if getattr(ann, "__origin__", None) is list:
                return JSON
            if isinstance(ann, types.UnionType):
                for arg in ann.__args__:
                    if getattr(arg, "__origin__", None) is list:
                        return JSON
            raise

    _sqlmodel_main.get_sqlalchemy_type = _patched_get_sqlalchemy_type

    # --- Fix 2: Make resource_id optional in SQLiteMemoryItemRepo.create_item
    from memu.database.sqlite.repositories.memory_item_repo import (
        SQLiteMemoryItemRepo,
    )

    _orig_create_item = SQLiteMemoryItemRepo.create_item

    def _patched_create_item(self, *, resource_id=None, **kwargs):
        return _orig_create_item(self, resource_id=resource_id, **kwargs)

    SQLiteMemoryItemRepo.create_item = _patched_create_item

    # --- Fix 3: Rename sqlite_* tables to memu_* (sqlite_ prefix is reserved)
    from memu.database.sqlite import models as _sqlite_models
    from memu.database.sqlite import schema as _sqlite_schema

    _orig_build = _sqlite_models.build_sqlite_table_model

    def _patched_build(user_model, core_model, *, tablename, **kwargs):
        if tablename.startswith("sqlite_"):
            tablename = "memu_" + tablename[len("sqlite_") :]
        return _orig_build(user_model, core_model, tablename=tablename, **kwargs)

    _sqlite_models.build_sqlite_table_model = _patched_build
    # schema.py imports build_sqlite_table_model at module level — patch that ref too
    _sqlite_schema.build_sqlite_table_model = _patched_build

    _PATCHED = True
