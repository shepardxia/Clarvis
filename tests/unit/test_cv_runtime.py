"""Tests for on-block runtime evaluation."""

from clarvis.display.cv.runtime import evaluate_on_blocks
from clarvis.display.cv.specs import OnBlock, OnCase


class TestEvaluateOnBlocks:
    def test_simple_match(self):
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

    def test_no_match_returns_empty(self):
        blocks = [
            OnBlock(
                context_key="status",
                cases=[OnCase(match="resting", overrides={"scale": 0.8})],
            )
        ]
        result = evaluate_on_blocks(blocks, {"status": "idle"})
        assert result == {}

    def test_range_match(self):
        blocks = [
            OnBlock(
                context_key="hour",
                cases=[OnCase(match="0..6", overrides={"skin": "sleepy"})],
            )
        ]
        result = evaluate_on_blocks(blocks, {"hour": 3})
        assert result["skin"] == "sleepy"

    def test_range_no_match(self):
        blocks = [
            OnBlock(
                context_key="hour",
                cases=[OnCase(match="0..6", overrides={"skin": "sleepy"})],
            )
        ]
        result = evaluate_on_blocks(blocks, {"hour": 12})
        assert result == {}

    def test_multiple_blocks_compose(self):
        blocks = [
            OnBlock(
                context_key="status",
                cases=[
                    OnCase(match="excited", overrides={"scale": 1.2}),
                ],
            ),
            OnBlock(
                context_key="hour",
                cases=[
                    OnCase(match="22..24", overrides={"skin": "sleepy"}),
                ],
            ),
        ]
        result = evaluate_on_blocks(blocks, {"status": "excited", "hour": 23})
        assert result["scale"] == 1.2
        assert result["skin"] == "sleepy"

    def test_bool_match(self):
        blocks = [
            OnBlock(
                context_key="voice_active",
                cases=[OnCase(match="true", overrides={"visible": True})],
            )
        ]
        result = evaluate_on_blocks(blocks, {"voice_active": True})
        assert result["visible"] is True

    def test_missing_context_key(self):
        blocks = [
            OnBlock(
                context_key="nonexistent",
                cases=[OnCase(match="anything", overrides={"x": 1})],
            )
        ]
        result = evaluate_on_blocks(blocks, {"status": "idle"})
        assert result == {}
