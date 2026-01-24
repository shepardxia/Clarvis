"""Tests for avatar frame generation."""

import pytest

from clarvis.widget.avatar import (
    BORDERS,
    EYES,
    EYE_POSITIONS,
    MOUTHS,
    SUBSTRATES,
    build_frame,
    get_frames,
    get_avatar_data,
)


class TestBuildFrame:
    """Tests for build_frame function."""

    def test_basic_structure(self):
        """Frame should have 5 lines with box characters."""
        frame = build_frame("idle")
        lines = frame.split("\n")
        assert len(lines) == 5
        # Top border
        assert lines[0].startswith("╭")
        assert lines[0].endswith("╮")
        # Eyes line
        assert lines[1].startswith("|")
        assert lines[1].endswith("|")
        # Mouth line
        assert lines[2].startswith("|")
        assert lines[2].endswith("|")
        # Substrate line
        assert lines[3].startswith("|")
        assert lines[3].endswith("|")
        # Bottom border
        assert lines[4].startswith("╰")
        assert lines[4].endswith("╯")

    def test_uses_status_border(self):
        """Frame should use border character for status."""
        frame = build_frame("thinking")
        assert BORDERS["thinking"] in frame

    def test_uses_status_eyes(self):
        """Frame should use eye character for status."""
        frame = build_frame("running")
        lines = frame.split("\n")
        eye = EYES["running"]
        assert eye in lines[1]

    def test_uses_status_mouth(self):
        """Frame should use mouth character for status."""
        frame = build_frame("awaiting")
        lines = frame.split("\n")
        mouth = MOUTHS["awaiting"]
        assert mouth in lines[2]

    def test_uses_status_substrate(self):
        """Frame should use substrate pattern for status."""
        frame = build_frame("reading", frame_index=0)
        lines = frame.split("\n")
        substrate = SUBSTRATES["reading"][0]
        assert substrate in lines[3]

    def test_frame_index_cycles_substrates(self):
        """Frame index should cycle through substrates."""
        # Reading has 4 substrate patterns
        substrates = SUBSTRATES["reading"]
        for i in range(len(substrates)):
            frame = build_frame("reading", frame_index=i)
            lines = frame.split("\n")
            assert substrates[i] in lines[3]

    def test_frame_index_cycles_eye_positions(self):
        """Frame index should cycle through eye positions."""
        # Thinking has 4 eye positions
        positions = EYE_POSITIONS["thinking"]
        frames = [build_frame("thinking", i) for i in range(len(positions))]
        # Different positions produce different eye lines
        eye_lines = [f.split("\n")[1] for f in frames]
        # At least some should be different (looking left vs right)
        assert len(set(eye_lines)) > 1

    def test_unknown_status_uses_defaults(self):
        """Unknown status should use fallback characters."""
        frame = build_frame("nonexistent")
        lines = frame.split("\n")
        assert len(lines) == 5
        # Should use fallback border ─
        assert "─" in lines[0]

    def test_all_known_statuses(self):
        """All defined statuses should generate valid frames."""
        for status in BORDERS.keys():
            frame = build_frame(status)
            lines = frame.split("\n")
            assert len(lines) == 5


class TestGetFrames:
    """Tests for get_frames function."""

    def test_returns_list_of_frames(self):
        """Should return a list of frame strings."""
        frames = get_frames("idle")
        assert isinstance(frames, list)
        assert all(isinstance(f, str) for f in frames)

    def test_frame_count_matches_max_patterns(self):
        """Frame count should match max of positions and substrates."""
        # Thinking has 4 positions and 2 substrates -> 4 frames
        frames = get_frames("thinking")
        positions = EYE_POSITIONS["thinking"]
        substrates = SUBSTRATES["thinking"]
        expected = max(len(positions), len(substrates))
        assert len(frames) == expected

    def test_single_frame_status(self):
        """Status with single pattern should have 1 frame."""
        # Idle has 1 position and 1 substrate
        frames = get_frames("idle")
        assert len(frames) == 1

    def test_multi_frame_status(self):
        """Status with multiple patterns should have multiple frames."""
        frames = get_frames("reading")
        assert len(frames) > 1


class TestGetAvatarData:
    """Tests for get_avatar_data function."""

    def test_returns_dict_with_required_keys(self):
        """Should return dict with status, frames, frame_count."""
        data = get_avatar_data("running")
        assert "status" in data
        assert "frames" in data
        assert "frame_count" in data

    def test_status_matches_input(self):
        """Status in data should match input."""
        data = get_avatar_data("thinking")
        assert data["status"] == "thinking"

    def test_frames_is_list(self):
        """Frames should be a list of strings."""
        data = get_avatar_data("idle")
        assert isinstance(data["frames"], list)
        assert all(isinstance(f, str) for f in data["frames"])

    def test_frame_count_matches_frames_length(self):
        """frame_count should equal len(frames)."""
        data = get_avatar_data("awaiting")
        assert data["frame_count"] == len(data["frames"])


class TestDataDictionaries:
    """Tests for data dictionaries consistency."""

    def test_all_borders_are_strings(self):
        """All border values should be single characters."""
        for status, border in BORDERS.items():
            assert isinstance(border, str), f"{status} border not string"
            assert len(border) == 1, f"{status} border not single char"

    def test_all_eyes_are_strings(self):
        """All eye values should be single characters."""
        for status, eye in EYES.items():
            assert isinstance(eye, str), f"{status} eye not string"
            assert len(eye) == 1, f"{status} eye not single char"

    def test_all_mouths_are_strings(self):
        """All mouth values should be single characters."""
        for status, mouth in MOUTHS.items():
            assert isinstance(mouth, str), f"{status} mouth not string"
            assert len(mouth) == 1, f"{status} mouth not single char"

    def test_eye_positions_are_valid_tuples(self):
        """Eye positions should be lists of (l, g, r) tuples summing to 7."""
        for status, positions in EYE_POSITIONS.items():
            assert isinstance(positions, list)
            for pos in positions:
                assert len(pos) == 3, f"{status} position wrong length"
                l, g, r = pos
                assert l + g + r == 7, f"{status} position doesn't sum to 7"

    def test_substrates_are_valid_length(self):
        """All substrates should be 9 characters (for width 11 frame)."""
        for status, patterns in SUBSTRATES.items():
            assert isinstance(patterns, list)
            for pattern in patterns:
                assert len(pattern) == 9, f"{status} substrate wrong length: {len(pattern)}"
