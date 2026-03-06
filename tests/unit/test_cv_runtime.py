"""Tests for on-block runtime evaluation."""

from clarvis.display.cv.runtime import evaluate_on_blocks
from clarvis.display.cv.specs import OnBlock, OnCase


def test_on_block_evaluation():
    """Walk through all match types: string, no-match, range hit, range miss, composition, bool."""

    # simple string match
    blocks = [
        OnBlock(
            context_key="status",
            cases=[
                OnCase(match="resting", overrides={"scale": 0.8}),
                OnCase(match="excited", overrides={"scale": 1.2}),
            ],
        )
    ]
    result = evaluate_on_blocks(blocks, {"status": "resting"})
    assert result["scale"] == 0.8

    # no match returns empty dict
    result = evaluate_on_blocks(blocks, {"status": "idle"})
    assert result == {}

    # range match — hour inside range
    range_blocks = [
        OnBlock(
            context_key="hour",
            cases=[OnCase(match="0..6", overrides={"skin": "sleepy"})],
        )
    ]
    result = evaluate_on_blocks(range_blocks, {"hour": 3})
    assert result["skin"] == "sleepy"

    # range miss — hour outside range
    result = evaluate_on_blocks(range_blocks, {"hour": 12})
    assert result == {}

    # multiple blocks compose their overrides
    multi_blocks = [
        OnBlock(
            context_key="status",
            cases=[OnCase(match="excited", overrides={"scale": 1.2})],
        ),
        OnBlock(
            context_key="hour",
            cases=[OnCase(match="22..24", overrides={"skin": "sleepy"})],
        ),
    ]
    result = evaluate_on_blocks(multi_blocks, {"status": "excited", "hour": 23})
    assert result["scale"] == 1.2
    assert result["skin"] == "sleepy"

    # bool match — True coerced to "true"
    bool_blocks = [
        OnBlock(
            context_key="voice_active",
            cases=[OnCase(match="true", overrides={"visible": True})],
        )
    ]
    result = evaluate_on_blocks(bool_blocks, {"voice_active": True})
    assert result["visible"] is True


def test_on_block_missing_context():
    """Missing context key is handled gracefully, returning empty overrides."""
    blocks = [
        OnBlock(
            context_key="nonexistent",
            cases=[OnCase(match="anything", overrides={"x": 1})],
        )
    ]
    result = evaluate_on_blocks(blocks, {"status": "idle"})
    assert result == {}
