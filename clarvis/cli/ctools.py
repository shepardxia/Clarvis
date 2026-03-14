"""ctools — Python CLI for Clarvis daemon services.

Usage: ctools <command> [args...] [key=value ...]
       ctools --help
       ctools --dump-grounding
"""

import inspect
import json
import sys
import types
import typing
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ParamSpec:
    name: str
    annotation: type | None
    default: Any  # inspect.Parameter.empty if required
    required: bool


@dataclass
class CommandSpec:
    ipc_name: str
    module_name: str
    params: list[ParamSpec] = field(default_factory=list)
    doc: str = ""


def _unwrap_optional(tp):
    """Unwrap T | None → T. Returns (inner_type, was_optional)."""
    origin = typing.get_origin(tp)
    if origin is types.UnionType or origin is typing.Union:
        args = [a for a in typing.get_args(tp) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
    return tp, False


def _is_list_of(tp, inner):
    """Check if tp is list[inner]."""
    return typing.get_origin(tp) is list and typing.get_args(tp) == (inner,)


def coerce_value(value_str: str, spec: ParamSpec) -> Any:
    """Convert a CLI string value to the type indicated by the ParamSpec annotation."""
    ann = spec.annotation
    if ann is None:
        # No annotation — try JSON parse, fall back to string
        try:
            return json.loads(value_str)
        except (json.JSONDecodeError, ValueError):
            return value_str

    # Unwrap Optional
    inner, _ = _unwrap_optional(ann)

    # Simple scalars
    if inner is str:
        return value_str
    if inner is int:
        return int(value_str)
    if inner is float:
        return float(value_str)
    if inner is bool:
        return value_str.lower() in ("true", "1", "yes")

    # list[str] — comma-separated
    if _is_list_of(inner, str):
        return [s.strip() for s in value_str.split(",")]

    # list[dict], dict, or other complex types — JSON parse
    if typing.get_origin(inner) is list or inner is list or inner is dict or typing.get_origin(inner) is dict:
        return json.loads(value_str)

    # Fallback: try JSON, then string
    try:
        return json.loads(value_str)
    except (json.JSONDecodeError, ValueError):
        return value_str


def _resolve_annotations(fn) -> dict[str, type]:
    """Resolve string annotations individually, skipping unresolvable ones (e.g. TYPE_CHECKING imports)."""
    hints = {}
    ns = {**vars(typing), **__builtins__} if isinstance(__builtins__, dict) else {**vars(typing), **vars(__builtins__)}
    # Add the function's module globals for any module-level names
    mod = inspect.getmodule(fn)
    if mod:
        ns.update(vars(mod))
    raw = fn.__annotations__ if hasattr(fn, "__annotations__") else {}
    for name, ann in raw.items():
        if name == "return":
            continue
        if isinstance(ann, str):
            try:
                hints[name] = eval(ann, ns)  # noqa: S307
            except Exception:
                pass
        else:
            hints[name] = ann
    return hints


def build_registry() -> dict[str, CommandSpec]:
    """Build command registry from domain module COMMANDS lists and handler signatures."""
    from clarvis.core.commands import _DOMAIN_MODULES

    registry: dict[str, CommandSpec] = {}
    for mod in _DOMAIN_MODULES:
        mod_label = mod.__name__.rsplit(".", 1)[-1]
        commands = getattr(mod, "COMMANDS", [])
        for name in commands:
            fn = getattr(mod, name, None)
            if fn is None:
                continue
            sig = inspect.signature(fn)
            try:
                hints = typing.get_type_hints(fn)
            except Exception:
                # from __future__ import annotations + TYPE_CHECKING guards
                # cause get_type_hints to fail. Resolve annotation strings manually.
                hints = _resolve_annotations(fn)

            params = []
            for p in sig.parameters.values():
                if p.name == "self" or p.name == "kw" or p.kind == p.VAR_KEYWORD:
                    continue
                params.append(
                    ParamSpec(
                        name=p.name,
                        annotation=hints.get(p.name),
                        default=p.default,
                        required=p.default is inspect.Parameter.empty,
                    )
                )

            doc = (fn.__doc__ or "").strip().split("\n")[0]
            registry[name] = CommandSpec(
                ipc_name=name,
                module_name=mod_label,
                params=params,
                doc=doc,
            )
    return registry


def _is_scalar_type(ann: type | None) -> bool:
    """Check if annotation is a simple scalar (eligible for positional args)."""
    if ann is None:
        return True
    inner, _ = _unwrap_optional(ann)
    return inner in (str, int, float, bool)


def parse_args(spec: CommandSpec, raw_args: list[str]) -> dict[str, Any]:
    """Parse positional and key=value arguments into a dict.

    Positional args (no ``=``) are matched to required params in declaration
    order.  Only scalar types (str/int/float/bool) accept positional values;
    complex types (list, dict) must use key=value.  Positional args must
    come before any key=value args.
    """
    result = {}
    param_map = {p.name: p for p in spec.params}

    # Split into positional (no '=') and keyword (has '=').
    # Positional must come before keyword.
    positional: list[str] = []
    keyword: list[str] = []
    seen_keyword = False
    for arg in raw_args:
        if "=" in arg:
            seen_keyword = True
            keyword.append(arg)
        else:
            if seen_keyword:
                raise ValueError(f"Positional argument after key=value: {arg}")
            positional.append(arg)

    # Match positional args to required params with scalar types
    positional_targets = [p for p in spec.params if p.required and _is_scalar_type(p.annotation)]
    if len(positional) > len(positional_targets):
        names = ", ".join(p.name for p in positional_targets) or "none"
        raise ValueError(
            f"Too many positional arguments ({len(positional)}) — accepts at most {len(positional_targets)} ({names})"
        )

    for val, ps in zip(positional, positional_targets):
        result[ps.name] = coerce_value(val, ps)

    # Process keyword args
    for arg in keyword:
        key, value = arg.split("=", 1)
        ps = param_map.get(key)
        if ps is None:
            # Unknown param — pass through as-is (handlers accept **kw)
            try:
                result[key] = json.loads(value)
            except (json.JSONDecodeError, ValueError):
                result[key] = value
            continue
        result[key] = coerce_value(value, ps)

    # Check required params
    missing = [p.name for p in spec.params if p.required and p.name not in result]
    if missing:
        raise ValueError(f"Missing required parameter(s): {', '.join(missing)}")

    return result


def _format_param(p: ParamSpec) -> str:
    """Format a single param for help display."""
    if p.required:
        return f"<{p.name}>"
    return f"{p.name}={p.default!r}"


def print_help(registry: dict[str, CommandSpec]) -> None:
    """Print help to stdout."""
    # Group by module
    by_module: dict[str, list[CommandSpec]] = {}
    for spec in registry.values():
        by_module.setdefault(spec.module_name, []).append(spec)

    for mod_name, specs in by_module.items():
        print(f"\n  {mod_name}")
        print(f"  {'─' * 40}")
        for spec in specs:
            positional = [_format_param(p) for p in spec.params if p.required]
            optional = [_format_param(p) for p in spec.params if not p.required]
            parts = " ".join(positional)
            if optional:
                parts += f"  [{', '.join(optional)}]"
            line = f"    {spec.ipc_name}  {parts}" if parts else f"    {spec.ipc_name}"
            print(line)
            if spec.doc:
                print(f"      {spec.doc}")
    print()


def _type_label(ann: type | None) -> str:
    """Human-readable type label for grounding output."""
    if ann is None:
        return "str"
    inner, _ = _unwrap_optional(ann)
    if inner is str:
        return "str"
    if inner is int:
        return "int"
    if inner is float:
        return "float"
    if inner is bool:
        return "bool"
    if _is_list_of(inner, str):
        return "list (comma-separated)"
    if inner is dict or (inner and typing.get_origin(inner) is dict):
        return "JSON"
    if inner and typing.get_origin(inner) is list:
        return "JSON array"
    return "str"


def print_grounding(registry: dict[str, CommandSpec]) -> None:
    """Print grounding markdown to stdout."""
    by_module: dict[str, list[CommandSpec]] = {}
    for spec in registry.values():
        by_module.setdefault(spec.module_name, []).append(spec)

    print("# ctools — Daemon Commands\n")
    print("Usage: `ctools <command> [args...] [key=value ...]`\n")

    for mod_name, specs in by_module.items():
        print(f"## {mod_name}\n")
        for spec in specs:
            # Build signature with positional args inline
            positional = [f"<{p.name}>" for p in spec.params if p.required]
            sig = " ".join(positional)
            header = f"**{spec.ipc_name}** {sig}" if sig else f"**{spec.ipc_name}**"
            print(f"{header} — {spec.doc}")

            # Only list optional params (required are shown in signature)
            optional = [p for p in spec.params if not p.required]
            for p in optional:
                print(f"  - `{p.name}` ({_type_label(p.annotation)}, default: {p.default!r})")
            print()


def main() -> None:
    """Entry point for ctools CLI."""
    args = sys.argv[1:]

    if not args or args[0] in ("--help", "-h"):
        registry = build_registry()
        print_help(registry)
        return

    if args[0] == "--dump-grounding":
        registry = build_registry()
        print_grounding(registry)
        return

    command = args[0]
    raw_args = args[1:]

    # Handle stdin pipe via '-' flag
    if raw_args == ["-"] or (not raw_args and not sys.stdin.isatty()):
        stdin_data = sys.stdin.read().strip()
        if stdin_data:
            # Try as JSON first (backward compat for piped JSON)
            try:
                params = json.loads(stdin_data)
                if isinstance(params, dict):
                    raw_args = [f"{k}={json.dumps(v) if not isinstance(v, str) else v}" for k, v in params.items()]
                else:
                    raw_args = []
            except (json.JSONDecodeError, ValueError):
                # Treat as key=value lines
                raw_args = [line.strip() for line in stdin_data.splitlines() if "=" in line]

    registry = build_registry()
    spec = registry.get(command)
    if spec is None:
        print(f"Unknown command: {command}", file=sys.stderr)
        print("Run 'ctools --help' to see available commands.", file=sys.stderr)
        sys.exit(1)

    try:
        params = parse_args(spec, raw_args)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Call daemon
    from clarvis.core.ipc import DaemonClient

    _SLOW_COMMANDS = {"web_research"}
    timeout = 300.0 if command in _SLOW_COMMANDS else 30.0

    try:
        client = DaemonClient(timeout=timeout)
        result = client.call(command, **params)
    except ConnectionError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    # Print result
    if result is None:
        pass
    elif isinstance(result, str):
        print(result)
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
