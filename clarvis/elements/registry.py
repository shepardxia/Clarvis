"""
Element registry - discovers, loads, caches, and hot-reloads YAML element definitions.
"""

import threading
from pathlib import Path
from typing import Any, Callable, Optional

import yaml
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent, FileCreatedEvent


class ElementChangeHandler(FileSystemEventHandler):
    """Watchdog handler that triggers registry reload on file changes."""

    def __init__(self, registry: "ElementRegistry"):
        self.registry = registry

    def on_modified(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(('.yaml', '.yml')):
            self.registry.reload(event.src_path)

    def on_created(self, event):
        if event.is_directory:
            return
        if event.src_path.endswith(('.yaml', '.yml')):
            self.registry.reload(event.src_path)


class ElementRegistry:
    """
    Central registry for all visual element definitions.

    Discovers and loads YAML files from element directories.
    Supports hot-reloading via file system watching.

    Usage:
        registry = ElementRegistry(['clarvis/elements'])
        registry.load_all()
        registry.start_watching()

        eyes = registry.get('eyes', 'normal')
        animation = registry.get('animations', 'thinking')
    """

    def __init__(self, paths: Optional[list[str]] = None):
        """
        Initialize registry with element directory paths.

        Args:
            paths: List of directory paths to search for elements.
                   Defaults to ['clarvis/elements'] relative to package.
        """
        if paths is None:
            # Default to package elements directory
            package_dir = Path(__file__).parent
            paths = [str(package_dir)]

        self.paths = [Path(p) for p in paths]
        self._elements: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._listeners: list[Callable[[str, str], None]] = []
        self._observers: list[Observer] = []
        self._watching = False

    def load_all(self) -> None:
        """Discover and load all YAML files from element paths."""
        with self._lock:
            self._elements.clear()
            for base_path in self.paths:
                if not base_path.exists():
                    continue
                for yaml_file in base_path.rglob('*.yaml'):
                    self._load_file(yaml_file)
                for yaml_file in base_path.rglob('*.yml'):
                    self._load_file(yaml_file)

    def _load_file(self, file_path: Path) -> Optional[dict]:
        """Load a single YAML file and register its contents."""
        try:
            with open(file_path, 'r') as f:
                data = yaml.safe_load(f)

            if not data:
                return None

            # Determine kind and name from file path
            # e.g., elements/eyes/normal.yaml -> kind='eyes', name='normal'
            kind, name = self._parse_path(file_path)

            # Store with kind as key
            if kind not in self._elements:
                self._elements[kind] = {}
            self._elements[kind][name] = data

            return data
        except (yaml.YAMLError, IOError) as e:
            # Log but don't crash on bad files
            print(f"Warning: Failed to load {file_path}: {e}")
            return None

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
                    return 'root', rel_path.stem
            except ValueError:
                continue

        # Fallback: use parent dir name and stem
        return file_path.parent.name, file_path.stem

    def get(self, kind: str, name: str) -> Optional[dict]:
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

    def get_all(self, kind: str) -> dict[str, Any]:
        """
        Get all elements of a given kind.

        Args:
            kind: Element category

        Returns:
            Dict mapping names to element definitions
        """
        with self._lock:
            return dict(self._elements.get(kind, {}))

    def list_kinds(self) -> list[str]:
        """List all available element kinds."""
        with self._lock:
            return list(self._elements.keys())

    def list_names(self, kind: str) -> list[str]:
        """List all element names for a given kind."""
        with self._lock:
            return list(self._elements.get(kind, {}).keys())

    def reload(self, file_path: str) -> None:
        """
        Reload a single element file and notify listeners.

        Args:
            file_path: Path to the changed YAML file
        """
        path = Path(file_path)
        kind, name = self._parse_path(path)

        with self._lock:
            self._load_file(path)

        # Notify listeners outside the lock
        self._notify_listeners(kind, name)

    def on_change(self, callback: Callable[[str, str], None]) -> None:
        """
        Register a callback for element changes.

        Args:
            callback: Function called with (kind, name) when an element changes
        """
        self._listeners.append(callback)

    def _notify_listeners(self, kind: str, name: str) -> None:
        """Notify all listeners of an element change."""
        for listener in self._listeners:
            try:
                listener(kind, name)
            except Exception as e:
                print(f"Warning: Listener error on {kind}/{name}: {e}")

    def start_watching(self) -> None:
        """Start watching element directories for changes."""
        if self._watching:
            return

        for base_path in self.paths:
            if not base_path.exists():
                continue
            observer = Observer()
            handler = ElementChangeHandler(self)
            observer.schedule(handler, str(base_path), recursive=True)
            observer.start()
            self._observers.append(observer)

        self._watching = True

    def stop_watching(self) -> None:
        """Stop watching element directories."""
        for observer in self._observers:
            observer.stop()
            observer.join()
        self._observers.clear()
        self._watching = False

    def __contains__(self, key: tuple[str, str]) -> bool:
        """Check if an element exists: ('eyes', 'normal') in registry"""
        kind, name = key
        return self.get(kind, name) is not None
