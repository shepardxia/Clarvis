"""
Element registry - discovers, loads, and caches YAML element definitions.
"""

import logging
import threading
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class ElementRegistry:
    """
    Central registry for all visual element definitions.

    Discovers and loads YAML files from element directories at startup.

    Usage:
        registry = ElementRegistry(['clarvis/display/elements'])
        registry.load_all()

        eyes = registry.get('eyes', 'normal')
        animation = registry.get('animations', 'thinking')
    """

    def __init__(self, paths: list[str] | None = None):
        """
        Initialize registry with element directory paths.

        Args:
            paths: List of directory paths to search for elements.
                   Defaults to ['clarvis/display/elements'] relative to package.
        """
        if paths is None:
            # Default to package elements directory
            package_dir = Path(__file__).parent
            paths = [str(package_dir)]

        self.paths = [Path(p) for p in paths]
        self._elements: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def load_all(self) -> None:
        """Discover and load all YAML files from element paths."""
        with self._lock:
            self._elements.clear()
            for base_path in self.paths:
                if not base_path.exists():
                    continue
                for yaml_file in base_path.rglob("*.yaml"):
                    self._load_file(yaml_file)
                for yaml_file in base_path.rglob("*.yml"):
                    self._load_file(yaml_file)

    def _load_file(self, file_path: Path) -> dict | None:
        """Load a single YAML file and register its contents."""
        try:
            with open(file_path, "r") as f:
                data = yaml.safe_load(f)

            if not data:
                return None

            # Determine kind and name from file path
            # e.g., elements/eyes/normal.yaml -> kind='eyes', name='normal'
            kind, name = self._parse_path(file_path)

            # Expand sequences for animations
            if kind == "animations" and "frames" in data:
                data = self._expand_sequences(data)

            # Store with kind as key
            if kind not in self._elements:
                self._elements[kind] = {}
            self._elements[kind][name] = data

            return data
        except (yaml.YAMLError, IOError) as e:
            # Log but don't crash on bad files
            logger.warning("Failed to load %s: %s", file_path, e)
            return None

    def _expand_sequences(self, data: dict) -> dict:
        """
        Expand sequence references in animation frames.

        Supports:
        - sequences: Define reusable frame snippets
        - $sequence_name: Reference to expand inline
        - $sequence_name*N: Repeat sequence N times

        Example YAML:
            sequences:
              blink:
                - { eyes: "◔" }
                - { eyes: "─" }
                - { eyes: "◔" }
              sparkle:
                - { eyes: "✧", border: "✦" }
                - { eyes: "✦", border: "✧" }

            frames:
              - { eyes: "◕", mouth: "◡" }
              - $blink
              - { eyes: "◕", mouth: "◡" }
              - $sparkle*2
        """
        sequences = data.get("sequences", {})
        frames = data.get("frames", [])

        if not sequences:
            return data

        expanded_frames = []
        for frame in frames:
            if isinstance(frame, str) and frame.startswith("$"):
                # Parse sequence reference: $name or $name*N
                ref = frame[1:]  # Remove $
                repeat = 1
                if "*" in ref:
                    ref, repeat_str = ref.split("*", 1)
                    repeat = int(repeat_str) if repeat_str.isdigit() else 1

                # Expand sequence
                if ref in sequences:
                    seq_frames = sequences[ref]
                    for _ in range(repeat):
                        expanded_frames.extend(seq_frames)
                else:
                    # Unknown sequence, keep as-is (will be ignored)
                    expanded_frames.append(frame)
            else:
                expanded_frames.append(frame)

        # Return modified data with expanded frames
        result = dict(data)
        result["frames"] = expanded_frames
        return result

    def _parse_path(self, file_path: Path) -> tuple[str, str]:
        """
        Parse file path to extract kind and name.

        Args:
            file_path: Path like /path/to/elements/eyes/normal.yaml

        Returns:
            Tuple of (kind, name) e.g., ('eyes', 'normal')
        """
        # Get relative path from any of our base paths
        for base_path in self.paths:
            try:
                rel_path = file_path.relative_to(base_path)
                parts = rel_path.parts
                if len(parts) >= 2:
                    kind = parts[0]
                    name = rel_path.stem  # filename without extension
                    return kind, name
                elif len(parts) == 1:
                    # File directly in elements/, use 'root' as kind
                    return "root", rel_path.stem
            except ValueError:
                continue

        # Fallback: use parent dir name and stem
        return file_path.parent.name, file_path.stem

    def get(self, kind: str, name: str) -> dict | None:
        """
        Retrieve an element by kind and name.

        Args:
            kind: Element category (e.g., 'eyes', 'mouths', 'animations')
            name: Element name (e.g., 'normal', 'thinking')

        Returns:
            Element definition dict, or None if not found
        """
        with self._lock:
            return self._elements.get(kind, {}).get(name)
