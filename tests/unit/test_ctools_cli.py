"""Tests for the Python ctools CLI — arg parsing, type coercion, and registry."""

import inspect
import io
from contextlib import redirect_stdout

from clarvis.cli.ctools import (
    CommandSpec,
    ParamSpec,
    build_registry,
    coerce_value,
    parse_args,
    print_grounding,
    print_help,
)

# --- Registry ---


def test_build_registry_discovers_all_commands():
    """Registry should contain all commands from all domain modules."""
    from clarvis.core.commands import _DOMAIN_MODULES

    expected = set()
    for mod in _DOMAIN_MODULES:
        expected.update(getattr(mod, "COMMANDS", {}).keys())

    registry = build_registry()
    assert set(registry.keys()) == expected
    assert len(registry) >= 30  # sanity check — we know there are ~30+


def test_build_registry_extracts_params():
    """Registry entries should have correct param metadata from handler signatures."""
    registry = build_registry()
    recall = registry["recall"]
    param_names = [p.name for p in recall.params]
    assert "query" in param_names
    assert "bank" in param_names
    assert "limit" in param_names

    # query is required, bank has default
    query_p = next(p for p in recall.params if p.name == "query")
    assert query_p.required is True
    bank_p = next(p for p in recall.params if p.name == "bank")
    assert bank_p.required is False
    assert bank_p.default == "parletre"


def test_build_registry_extracts_docstrings():
    """Registry entries should include first line of handler docstring."""
    registry = build_registry()
    assert "Search memory" in registry["recall"].doc
    assert "timer" in registry["timer"].doc.lower() or "Timer" in registry["timer"].doc


# --- Coercion ---


def _spec(name: str, ann: type | None, default=inspect.Parameter.empty) -> ParamSpec:
    return ParamSpec(name=name, annotation=ann, default=default, required=default is inspect.Parameter.empty)


def test_coerce_str():
    assert coerce_value("hello world", _spec("x", str)) == "hello world"


def test_coerce_int():
    assert coerce_value("5", _spec("x", int)) == 5


def test_coerce_float():
    assert coerce_value("0.75", _spec("x", float)) == 0.75


def test_coerce_bool_true():
    assert coerce_value("true", _spec("x", bool)) is True
    assert coerce_value("1", _spec("x", bool)) is True
    assert coerce_value("yes", _spec("x", bool)) is True


def test_coerce_bool_false():
    assert coerce_value("false", _spec("x", bool)) is False
    assert coerce_value("0", _spec("x", bool)) is False
    assert coerce_value("no", _spec("x", bool)) is False


def test_coerce_list_str():
    assert coerce_value("music,jazz", _spec("x", list[str])) == ["music", "jazz"]


def test_coerce_list_str_single():
    assert coerce_value("music", _spec("x", list[str])) == ["music"]


def test_coerce_list_str_spaces():
    """Comma-separated values should be stripped of whitespace."""
    assert coerce_value("music, jazz, blues", _spec("x", list[str])) == ["music", "jazz", "blues"]


def test_coerce_list_dict():
    raw = '[{"action":"create","text":"obs"}]'
    result = coerce_value(raw, _spec("x", list[dict]))
    assert result == [{"action": "create", "text": "obs"}]


def test_coerce_dict():
    raw = '{"key": "value"}'
    result = coerce_value(raw, _spec("x", dict))
    assert result == {"key": "value"}


def test_coerce_optional_str():
    """str | None should coerce as str."""
    assert coerce_value("hello", _spec("x", str | None, default=None)) == "hello"


def test_coerce_optional_int():
    """int | None should coerce as int."""
    assert coerce_value("42", _spec("x", int | None, default=None)) == 42


def test_coerce_optional_list_str():
    """list[str] | None should coerce as list[str]."""
    assert coerce_value("a,b,c", _spec("x", list[str] | None, default=None)) == ["a", "b", "c"]


def test_coerce_no_annotation_json():
    """No annotation + valid JSON → parsed JSON."""
    assert coerce_value("42", _spec("x", None)) == 42
    assert coerce_value("[1,2]", _spec("x", None)) == [1, 2]


def test_coerce_no_annotation_string_fallback():
    """No annotation + invalid JSON → string."""
    assert coerce_value("plain text", _spec("x", None)) == "plain text"


# --- Parsing ---


def test_parse_args_basic_kv():
    spec = CommandSpec(
        ipc_name="recall",
        module_name="memory",
        params=[
            _spec("query", str),
            _spec("bank", str, default="parletre"),
            _spec("limit", int, default=50),
        ],
    )
    result = parse_args(spec, ["query=music taste", "bank=agora", "limit=5"])
    assert result == {"query": "music taste", "bank": "agora", "limit": 5}


def test_parse_args_apostrophe():
    """Apostrophes in values should pass through cleanly — the whole point of this rewrite."""
    spec = CommandSpec(
        ipc_name="remember",
        module_name="memory",
        params=[_spec("text", str), _spec("fact_type", str, default="world")],
    )
    result = parse_args(spec, ["text=Sky's approach is experimental", "fact_type=world"])
    assert result["text"] == "Sky's approach is experimental"


def test_parse_args_defaults():
    """Omitted optional params should not appear in result (handler defaults apply)."""
    spec = CommandSpec(
        ipc_name="recall",
        module_name="memory",
        params=[
            _spec("query", str),
            _spec("bank", str, default="parletre"),
        ],
    )
    result = parse_args(spec, ["query=test"])
    assert result == {"query": "test"}
    assert "bank" not in result


def test_parse_args_missing_required():
    spec = CommandSpec(
        ipc_name="recall",
        module_name="memory",
        params=[_spec("query", str)],
    )
    try:
        parse_args(spec, [])
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "query" in str(e)


def test_parse_args_unknown_param_passthrough():
    """Unknown params should be passed through (handlers accept **kw)."""
    spec = CommandSpec(ipc_name="test", module_name="test", params=[])
    result = parse_args(spec, ["extra=value"])
    assert result == {"extra": "value"}


def test_parse_args_invalid_format():
    spec = CommandSpec(ipc_name="test", module_name="test", params=[])
    try:
        parse_args(spec, ["no-equals-sign"])
        assert False, "Should have raised ValueError"
    except ValueError as e:
        assert "key=value" in str(e)


def test_parse_args_value_with_equals():
    """Values containing '=' should be handled (split on first '=' only)."""
    spec = CommandSpec(
        ipc_name="remember",
        module_name="memory",
        params=[_spec("text", str)],
    )
    result = parse_args(spec, ["text=a=b=c"])
    assert result["text"] == "a=b=c"


# --- Help / grounding output ---


def test_print_help_contains_commands():
    registry = build_registry()
    buf = io.StringIO()
    with redirect_stdout(buf):
        print_help(registry)
    output = buf.getvalue()
    assert "recall" in output
    assert "remember" in output
    assert "timer" in output
    assert "spotify" in output


def test_print_grounding_format():
    registry = build_registry()
    buf = io.StringIO()
    with redirect_stdout(buf):
        print_grounding(registry)
    output = buf.getvalue()
    # Should be markdown
    assert "# ctools" in output
    assert "**recall**" in output
    assert "required" in output
    assert "default:" in output
