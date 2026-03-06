"""Loads .cv files from a directory, indexes blocks by type + name + tags."""

from __future__ import annotations

from pathlib import Path

from .parser import parse_cv
from .specs import PaletteSpec, SceneSpec, SequenceSpec, TemplateSpec


class CvRegistry:
    """Registry of parsed .cv specs with tag-based queries."""

    def __init__(self, directory: Path):
        self._directory = directory
        self._palettes: dict[str, PaletteSpec] = {}
        self._templates: dict[str, TemplateSpec] = {}
        self._sequences: dict[str, SequenceSpec] = {}
        self._scenes: dict[str, SceneSpec] = {}

    def load(self):
        """Parse all .cv files in the directory. Clears previous state."""
        self._palettes.clear()
        self._templates.clear()
        self._sequences.clear()
        self._scenes.clear()

        for cv_file in sorted(self._directory.glob("*.cv")):
            text = cv_file.read_text(encoding="utf-8")
            for block in parse_cv(text):
                if isinstance(block, PaletteSpec):
                    self._palettes[block.name] = block
                elif isinstance(block, TemplateSpec):
                    self._templates[block.name] = block
                elif isinstance(block, SequenceSpec):
                    self._sequences[block.name] = block
                elif isinstance(block, SceneSpec):
                    self._scenes[block.name] = block

    # --- Name lookups ---

    def get_palette(self, name: str) -> PaletteSpec | None:
        return self._palettes.get(name)

    def get_template(self, name: str) -> TemplateSpec | None:
        return self._templates.get(name)

    def get_scene(self, name: str) -> SceneSpec | None:
        return self._scenes.get(name)

    # --- Tag queries ---

    def query_palettes(self, tags: list[str] | None = None) -> list[PaletteSpec]:
        return self._query(self._palettes, tags)

    def query_sequences(self, tags: list[str] | None = None) -> list[SequenceSpec]:
        return self._query(self._sequences, tags)

    @staticmethod
    def _query(store: dict[str, PaletteSpec | SequenceSpec], tags: list[str] | None):
        if tags is None:
            return list(store.values())
        tag_set = set(tags)
        return [spec for spec in store.values() if not spec.tags or tag_set.intersection(spec.tags)]
