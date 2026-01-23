"""Avatar frame generation for the Claude status widget."""

from dataclasses import dataclass


# Avatar components by status
BORDERS = {
    "working": "═",
    "running": "═",
    "executing": "═",
    "thinking": "~",
    "reviewing": "~",
    "awaiting": "⋯",
    "reading": "·",
    "writing": "▪",
    "offline": "·",
    "idle": "─",
    "resting": "─",
}

EYES = {
    "idle": "·",
    "resting": "·",
    "thinking": "˘",
    "working": "●",
    "running": "●",
    "awaiting": "?",
    "offline": "·",
    "reading": "◦",
    "writing": "●",
    "executing": "●",
    "reviewing": "˘",
}

# Eye positions as (left_pad, gap, right_pad) - must sum to 7 for width 11
EYE_POSITIONS = {
    "idle": [(3, 1, 3)],
    "resting": [(3, 1, 3)],
    "thinking": [(3, 1, 3), (4, 1, 2), (3, 1, 3), (2, 1, 4)],
    "working": [(3, 1, 3)],
    "running": [(3, 1, 3)],
    "awaiting": [(3, 1, 3), (4, 1, 2), (3, 1, 3), (2, 1, 4)],
    "offline": [(3, 1, 3)],
    "reading": [(3, 1, 3), (4, 1, 2), (3, 1, 3), (2, 1, 4)],
    "writing": [(3, 1, 3)],
    "executing": [(3, 1, 3)],
    "reviewing": [(3, 1, 3), (4, 1, 2), (3, 1, 3), (2, 1, 4)],
}

MOUTHS = {
    "idle": "◡",
    "resting": "◡",
    "thinking": "~",
    "working": "◡",
    "running": "◡",
    "awaiting": "·",
    "offline": "─",
    "reading": "○",
    "writing": "◡",
    "executing": "▬",
    "reviewing": "~",
}

# Substrate patterns (activity indicators at bottom)
SUBSTRATES = {
    "idle": [" ·  ·  · "],
    "resting": [" ·  ·  · ", "·  ·  ·  ", " ·  ·  · ", "  ·  ·  ·"],
    "thinking": [" • ◦ • ◦ ", " ◦ • ◦ • "],
    "working": [" • ● • ● ", " ● • ● • "],
    "running": [" • ● • ● ", " ● • ● • "],
    "awaiting": [" · · · · ", "· · · ·  ", " · · · · ", "  · · · ·"],
    "offline": ["  · · ·  "],
    "reading": [" ▸ · · · ", " · ▸ · · ", " · · ▸ · ", " · · · ▸ "],
    "writing": [" ▪ ▪ ▪ ▪ ", " ▫ ▪ ▪ ▪ ", " ▫ ▫ ▪ ▪ ", " ▫ ▫ ▫ ▪ "],
    "executing": [" ▶ ▶ ▶ ▶ ", " ▷ ▶ ▶ ▶ ", " ▷ ▷ ▶ ▶ ", " ▷ ▷ ▷ ▶ "],
    "reviewing": [" ◇ ◇ ◇ ◇ ", " ◆ ◇ ◇ ◇ ", " ◆ ◆ ◇ ◇ ", " ◆ ◆ ◆ ◇ "],
}


def build_frame(status: str, frame_index: int = 0) -> str:
    """Build a single avatar frame for the given status."""
    border = BORDERS.get(status, "─")
    eye = EYES.get(status, "·")
    positions = EYE_POSITIONS.get(status, [(3, 1, 3)])
    mouth = MOUTHS.get(status, "◡")
    substrates = SUBSTRATES.get(status, ["  · · ·  "])

    pos = positions[frame_index % len(positions)]
    sub = substrates[frame_index % len(substrates)]
    l, g, r = pos

    return f"""╭{border * 9}╮
|{' ' * l}{eye}{' ' * g}{eye}{' ' * r}|
|    {mouth}    |
|{sub}|
╰{border * 9}╯"""


def get_frames(status: str):
    """Get all animation frames for a status."""
    positions = EYE_POSITIONS.get(status, [(3, 1, 3)])
    substrates = SUBSTRATES.get(status, ["  · · ·  "])
    frame_count = max(len(positions), len(substrates))

    return [build_frame(status, i) for i in range(frame_count)]


def get_avatar_data(status: str) -> dict:
    """Get avatar data for writing to hub JSON."""
    return {
        "status": status,
        "frames": get_frames(status),
        "frame_count": len(get_frames(status)),
    }


if __name__ == "__main__":
    # Test output
    for status in ["running", "thinking", "awaiting", "idle"]:
        print(f"\n=== {status} ===")
        frames = get_frames(status)
        for i, frame in enumerate(frames):
            print(f"Frame {i}:")
            print(frame)
