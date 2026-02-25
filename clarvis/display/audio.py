"""macOS system sound playback."""

import asyncio


async def play_system_sound(sound: str = "Glass") -> None:
    """Play a macOS system sound via ``afplay`` (fire-and-forget safe)."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "afplay",
            f"/System/Library/Sounds/{sound}.aiff",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
    except Exception:
        pass
