"""Spotify DSL MCP sub-server — mounted onto the main Clarvis server.

Single tool that accepts DSL command strings via the clautify package.
Formats raw responses as concise text for LLM consumption.
"""

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from typing import Annotated, Any

from fastmcp import Context, FastMCP
from pydantic import Field

logger = logging.getLogger(__name__)

# --- Default session factory (lazy init) ---

_session_cache = {}


def _default_get_session():
    """Lazy SpotifySession singleton. Re-attempts on each call if previous init failed."""
    if "instance" not in _session_cache:
        from clautify.dsl import SpotifySession

        session = SpotifySession.from_config(eager=False)
        # Apply max volume from Clarvis config
        try:
            from ..display.config import get_config

            session.max_volume = get_config().music.max_volume / 100
        except Exception:
            pass
        check = session.health_check()
        if check.get("authenticated"):
            logger.info("Spotify health check passed")
            _session_cache["instance"] = session
        else:
            logger.warning("Spotify health check FAILED: %s", check.get("error", "unknown"))
            # Don't cache — next call will retry
            return session
    return _session_cache["instance"]


# --- Formatting helpers ---


def _dig(d: Any, *keys: str, default: Any = None) -> Any:
    """Safely navigate nested dicts: _dig(d, 'a', 'b') == d['a']['b']."""
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k)
        else:
            return default
    return d if d is not None else default


def _ms_to_timestamp(ms: Any) -> str:
    """Convert milliseconds (int or str) to M:SS format."""
    try:
        total_s = int(ms) // 1000
    except (TypeError, ValueError):
        return "?"
    m, s = divmod(total_s, 60)
    return f"{m}:{s:02d}"


def _bare_id(uri: str) -> str:
    """Extract the 22-char bare ID from a spotify URI, or return as-is."""
    if uri and ":" in uri:
        return uri.rsplit(":", 1)[-1]
    return uri


def _first_artist(artists_node: Any, fallback: str = "?") -> str:
    """Extract the first artist name from a Spotify artists dict or items list."""
    try:
        items = artists_node.get("items", []) if isinstance(artists_node, dict) else artists_node
        return items[0].get("profile", {}).get("name", fallback) if items else fallback
    except (KeyError, TypeError, IndexError, AttributeError):
        return fallback


def _track_line(name: str, artist: str = "", album: str = "") -> str:
    """Format 'Name - Artist (Album)', omitting blank parts."""
    line = name or "?"
    if artist:
        line += f" - {artist}"
    if album:
        line += f" ({album})"
    return line


def _resolve_track(track) -> str | None:
    """Extract a displayable line from a track (dataclass or dict), or None."""
    if hasattr(track, "metadata"):
        m = track.metadata
        if m and m.title:
            return m.title
        return None
    if isinstance(track, dict):
        return track.get("name") or track.get("title")
    return None


def _section(label: str, items: list) -> list[str]:
    """['', 'Label:', 'a, b, c'] if any truthy items, else []."""
    items = [i for i in items if i]
    return ["", f"{label}:", ", ".join(items)] if items else []


# --- Query formatters ---


def _fmt_search(result: dict, session) -> str:
    kind = result.get("kind", "track")
    data = result.get("data")
    if not isinstance(data, list) or not data:
        return "No results."

    lines = []
    for item in data:
        try:
            if kind == "artist":
                name = _dig(item, "data", "profile", "name", default="?")
                uri = _dig(item, "data", "uri", default="")
                bid = _bare_id(uri) if uri else ""
                lines.append(f"{bid}  {name}" if bid else name)
            elif kind == "track":
                d = _dig(item, "item", "data", default={})
                uri = d.get("uri", "")
                bid = _bare_id(uri) if uri else ""
                display = _track_line(
                    d.get("name", "?"),
                    _first_artist(d.get("artists", {})),
                    _dig(d, "albumOfTrack", "name", default=""),
                )
                lines.append(f"{bid}  {display}" if bid else display)
            elif kind == "album":
                d = _dig(item, "data", default={})
                uri = d.get("uri", "")
                bid = _bare_id(uri) if uri else ""
                display = _track_line(d.get("name", "?"), _first_artist(d.get("artists", {})))
                lines.append(f"{bid}  {display}" if bid else display)
            elif kind == "playlist":
                d = _dig(item, "data", default={})
                uri = d.get("uri", "")
                bid = _bare_id(uri) if uri else ""
                owner = _dig(d, "ownerV2", "data", "name", default="?")
                count = _dig(d, "content", "totalCount")
                display = f"{d.get('name', '?')} - {owner}"
                if count:
                    display += f" ({count} tracks)"
                lines.append(f"{bid}  {display}" if bid else display)
            else:
                lines.append(_dig(item, "data", "name", default="?"))
        except (KeyError, TypeError, IndexError):
            continue
    return "\n".join(lines) if lines else "No results."


def _fmt_status(result: dict, session) -> str:
    sections = []

    # Now playing
    state = result.get("now_playing")
    if state and hasattr(state, "track") and state.track:
        m = state.track.metadata
        title = m.title if m else "?"
        album = m.album_title if m else ""
        line = _track_line(title, "", album)

        if state.is_paused is True or state.is_playing is False:
            sections.append(f"Playing:\n{line} (paused)")
        else:
            pos = _ms_to_timestamp(state.position_as_of_timestamp)
            dur = _ms_to_timestamp(state.duration)
            modes = []
            if state.options:
                if state.options.shuffling_context:
                    modes.append("shuffle")
                if state.options.repeating_context:
                    modes.append("repeat")
            info = f"{pos} / {dur}"
            if modes:
                info += ", " + ", ".join(modes)
            sections.append(f"Playing:\n{line}\n{info}")
    else:
        sections.append("Nothing playing.")

    # Queue
    queue = result.get("queue")
    if queue:
        lines = [_resolve_track(t) or "?" for t in queue]
        sections.append("Queue:\n" + "\n".join(lines))

    # History
    history = result.get("history")
    if history:
        lines = [_resolve_track(t) or "?" for t in history]
        sections.append("History:\n" + "\n".join(lines))

    # Devices
    devices = result.get("devices")
    if devices:
        sections.append("Devices:\n" + _fmt_devices({"data": devices}, session))

    return "\n\n".join(sections)


def _fmt_devices(result: dict, session) -> str:
    data = result.get("data")
    if data is None:
        return "No devices."

    lines = []
    if hasattr(data, "devices"):
        active_id = data.active_device_id
        for dev_id, dev in data.devices.items():
            vol_pct = round(dev.volume / 65535 * 100) if dev.volume is not None else "?"
            active = ", currently used" if dev_id == active_id else ""
            lines.append(f"{dev.name} ({dev.device_type.title()}{active}, vol: {vol_pct}%)")
    elif isinstance(data, dict):
        for dev_id, dev in data.items():
            lines.append(dev.get("name", dev_id) if isinstance(dev, dict) else str(dev))

    return "\n".join(lines) if lines else "No devices."


def _fmt_queue_or_history(result: dict, session) -> str:
    data = result.get("data")
    if not data:
        return "Empty."
    if not isinstance(data, list):
        data = [data]

    cap = result.get("limit", 10)
    lines = []
    unknown = 0

    for track in data[:cap]:
        line = _resolve_track(track)
        if line:
            lines.append(line)
        else:
            unknown += 1

    if unknown:
        lines.append(f"...and {unknown} untitled tracks")
    remaining = len(data) - cap
    if remaining > 0:
        lines.append(f"...and {remaining} more in queue")

    return "\n".join(lines) if lines else "Empty."


def _fmt_recommend(result: dict, session) -> str:
    tracks = _dig(result, "data", "recommendedTracks", default=[])
    if not tracks:
        return "No recommendations."

    lines = []
    for t in tracks:
        try:
            artists = t.get("artists", [])
            artist = artists[0]["name"] if artists else "?"
            lines.append(_track_line(t["name"], artist, _dig(t, "album", "name", default="")))
        except (KeyError, TypeError, IndexError):
            continue
    return "\n".join(lines) if lines else "No recommendations."


def _fmt_library_list(result: dict, session) -> str:
    items = _dig(result, "data", "data", "me", "libraryV3", "items")
    if not items:
        return "Library empty."

    cap = result.get("limit") or 50

    # Detect current user for my-vs-saved classification
    user_name = None
    for item in items:
        uri = _dig(item, "item", "data", "ownerV2", "data", "uri", default="")
        if uri.startswith("spotify:user:"):
            user_name = _dig(item, "item", "data", "ownerV2", "data", "name")
            break

    buckets: dict[str, list[str]] = {
        "My Playlists": [],
        "Albums": [],
        "Following": [],
        "Saved Playlists": [],
    }

    for item in items:
        d = _dig(item, "item", "data", default={})
        typename = d.get("__typename", "")
        name = d.get("name", "?")

        if any(kw in typename.lower() for kw in ("podcast", "show", "audiobook", "episode")):
            continue

        if "PseudoPlaylist" in typename:
            if "episode" in name.lower():
                continue
            buckets["My Playlists"].append(f"{name} ({d.get('count', '?')} tracks)")
        elif "Playlist" in typename:
            owner = _dig(d, "ownerV2", "data", "name", default="?")
            if user_name and owner == user_name:
                buckets["My Playlists"].append(name)
            else:
                buckets["Saved Playlists"].append(f"{name} by {owner}")
        elif "Album" in typename:
            buckets["Albums"].append(_track_line(name, _first_artist(d.get("artists", {}))))
        elif "Artist" in typename:
            buckets["Following"].append(_dig(d, "profile", "name", default=name))

    sections = []
    for label, entries in buckets.items():
        if entries:
            sections.append(f"{label}:\n" + "\n".join(f"  {e}" for e in entries[:cap]))

    return "\n\n".join(sections) if sections else "Library empty."


def _fmt_info(result: dict, session) -> str:
    kind = result.get("kind", "track")
    data = result.get("data")
    if not data:
        return "No info available."

    try:
        if kind == "artist":
            a = _dig(data, "data", "artistUnion", default={})
            name = _dig(a, "profile", "name", default="?")
            listeners = _dig(a, "stats", "monthlyListeners", default=0)
            rank = _dig(a, "stats", "worldRank")
            stats = [f"{listeners:,} monthly listeners" if listeners else "", f"#{rank} worldwide" if rank else ""]
            lines = [name] + ([", ".join(s for s in stats if s)] if any(stats) else [])

            bio = _dig(a, "profile", "biography", "text", default="")
            if bio:
                bio = re.sub(r"<[^>]+>", "", bio).split("\n")[0].strip()[:300]
                if bio:
                    lines += ["", bio]

            lines += _section(
                "Top tracks",
                [_dig(t, "track", "name") for t in _dig(a, "discography", "topTracks", "items", default=[])[:5]],
            )

            album_names = []
            for al in _dig(a, "discography", "albums", "items", default=[])[:10]:
                r = (_dig(al, "releases", "items") or [{}])[0]
                if r.get("name"):
                    y = _dig(r, "date", "year", default="")
                    album_names.append(f"{r['name']} ({y})" if y else r["name"])
            lines += _section("Albums", album_names)
            lines += _section(
                "Related artists",
                [
                    _dig(r, "profile", "name")
                    for r in _dig(a, "relatedContent", "relatedArtists", "items", default=[])[:10]
                ],
            )
            return "\n".join(lines)

        if kind == "album":
            al = _dig(data, "data", "albumUnion", default={})
            name, artist = al.get("name", "?"), _first_artist(al.get("artists", {}))
            year = _dig(al, "date", "year") or (_dig(al, "date", "isoString", default="") or "")[:4]
            meta = [s for s in [str(year) if year else "", al.get("label", "")] if s]
            header = f"{name} by {artist}" + (f" ({', '.join(meta)})" if meta else "")
            tracks = [
                _dig(t, "track", "name") for t in (_dig(al, "tracksV2", "items") or _dig(al, "tracks", "items") or [])
            ]
            tracks = [n for n in tracks if n]
            return header + ("\n" + ", ".join(tracks) if tracks else "")

        if kind == "playlist":
            pl = _dig(data, "data", "playlistV2", default={})
            owner = _dig(pl, "ownerV2", "data", "name", default="?")
            total = _dig(pl, "content", "totalCount", default="?")
            lines = [f"{pl.get('name', '?')} by {owner} - {total} tracks"]
            items = _dig(pl, "content", "items", default=[])
            for item in items[:20]:
                try:
                    td = _dig(item, "itemV2", "data", default={})
                    lines.append(_track_line(td.get("name", "?"), _first_artist(td.get("artists", {}))))
                except (KeyError, TypeError, IndexError):
                    continue
            if len(items) > 20:
                lines.append(f"...and {len(items) - 20} more")
            return "\n".join(lines)

        # track (default)
        t = _dig(data, "data", "trackUnion", default={})
        duration = _dig(t, "duration", "totalMilliseconds")
        playcount = t.get("playcount")
        line = _track_line(
            t.get("name", "?"), _first_artist(t.get("firstArtist", {})), _dig(t, "albumOfTrack", "name", default="")
        )
        meta = [_ms_to_timestamp(duration) if duration else ""]
        if playcount:
            try:
                meta.append(f"{int(playcount):,} plays")
            except (ValueError, TypeError):
                pass
        meta = [m for m in meta if m]
        return line + ("\n" + ", ".join(meta) if meta else "")

    except (KeyError, TypeError, IndexError):
        return str(data)[:2000]


# --- Action formatter ---


def _fmt_action(result: dict, session=None) -> str:
    action = result.get("action", "")
    target = result.get("target", "")

    if action == "pause":
        return "Paused"
    if action == "resume":
        return "Resumed"
    if action == "library_add":
        kind = result.get("kind", "")
        playlist = result.get("playlist")
        if playlist:
            return f"Added {target} to {playlist}"
        return f"Added {kind} {target} to library"
    if action == "library_remove":
        kind = result.get("kind", "")
        playlist = result.get("playlist")
        if playlist:
            return f"Removed {target} from {playlist}"
        return f"Removed {kind} {target} from library"
    if action == "library_create":
        return f'Created playlist "{target}"'
    if action == "library_delete":
        return f"Deleted playlist {target}"
    if action == "skip":
        n = result.get("n", 1)
        if abs(n) == 1:
            return "Skipped back" if n < 0 else "Skipped"
        return f"Skipped {'back ' if n < 0 else ''}{abs(n)} tracks"
    if action == "seek":
        pos = result.get("position_ms")
        return f"Seeked to {_ms_to_timestamp(pos)}" if pos else "Seeked"
    if action == "play":
        kind = result.get("kind", "")
        return f"Playing {kind + ' ' if kind in ('album', 'playlist') else ''}{target}"
    if action == "queue":
        targets = result.get("targets", [target] if target else [])
        if len(targets) == 1:
            return f"Added {targets[0]} to queue"
        return f"Queued {len(targets)} tracks:\n" + "\n".join(f"  {n}" for n in targets)
    if action == "set":
        parts = []
        if "volume" in result:
            parts.append(f"Volume set to {int(result['volume'])}%")
        if "volume_rel" in result:
            v = result["volume_rel"]
            parts.append(f"Volume {'+' if v > 0 else ''}{v}%")
        if "mode" in result:
            parts.append({"shuffle": "Shuffle on", "repeat": "Repeat on"}.get(result["mode"], "Normal playback"))
        if "device" in result:
            parts.append(f"Playing on {result['device']}")
        return ", ".join(parts) if parts else "OK"
    return "OK"


# --- Main formatter ---

_QUERY_FORMATTERS = {
    "search": _fmt_search,
    "status": _fmt_status,
    "recommend": _fmt_recommend,
    "library_list": _fmt_library_list,
    "info": _fmt_info,
}


def _format_result(result: dict, session) -> str:
    """Format a clautify DSL result as concise text for LLM consumption."""
    if not isinstance(result, dict):
        return str(result)
    if "error" in result:
        return result["error"]

    try:
        query = result.get("query")
        if query:
            fmt = _QUERY_FORMATTERS.get(query)
            if fmt:
                return fmt(result, session)
        elif result.get("action"):
            return _fmt_action(result, session)
    except Exception:
        logger.warning("Formatter error for %s", result.get("query") or result.get("action"), exc_info=True)

    raw = str(result)
    return raw[:2000] + "... (truncated)" if len(raw) > 2000 else raw


# --- Tool ---


async def clautify(
    command: Annotated[
        str,
        Field(description="A Spotify command."),
    ],
    ctx: Context = None,
) -> str:
    """Control Spotify playback, search, and library.

    ACTIONS: play, pause, resume, skip, seek, queue
             library add/remove/list/create/delete

    QUERIES: search, info, recommend, status

    MODIFIERS: volume, mode (shuffle/repeat/normal), device
               limit, offset (for query results)

    When acting on a specific item, specify its kind (track/album/artist/playlist) and target:

        search artist "radiohead"

    Targets are either a quoted "name" (resolved via fuzzy match) or a
    Spotify ID returned in search results.

        search track "karma police"          # returns IDs
        play album "OK Computer Radiohead"   # fuzzy match works better with artist name included
        play track 6rqhFgbbKwnb9MLmUQDhG6   # prefer IDs for exact matches
        info album 6dVIqQ8qmQ5GBnJ9shOYGE   # richer detail than search
        status                               # now playing, queue, devices, history
        library list playlist limit 10                # 10 saved playlists

    Queue and library add/remove are batchable:

        queue track "Karma Police" "Paranoid Android"

    Use play for albums and playlists.

    Use "in <kind> <target>" for destination context. Kind is required:

        library add track "Bohemian Rhapsody" in playlist "Classics"
        recommend track 5 in playlist "丁A之之"

    Limit and offset work on any query:

        search track "karma police" limit 3

    Playback modifiers work standalone or chained onto actions:

        play playlist "Rages Cupped" mode shuffle volume 60
        volume +10 device "Den"  # standalone (Den is the preferred device)
        skip -2                              # negative = go back
        seek 30                              # jump to 0:30

    """
    get_session = ctx.fastmcp._lifespan_result["get_session"]
    loop = asyncio.get_running_loop()

    try:

        def _run():
            session = get_session()
            return session.run(command), session

        result, session = await loop.run_in_executor(None, _run)
    except Exception as e:
        return str(e)

    return _format_result(result, session)


# --- Sub-server factory ---
_TOOLS = [clautify]


def create_spotify_server(get_session=None):
    """Create the Spotify DSL MCP sub-server.

    Args:
        get_session: Callable returning a SpotifySession instance. Defaults to
            lazy singleton via from_config(). Pass a mock factory for testing.
    """
    factory = get_session or _default_get_session

    @asynccontextmanager
    async def session_lifespan(server):
        yield {"get_session": factory}

    srv = FastMCP("clautify", lifespan=session_lifespan)
    for fn in _TOOLS:
        srv.tool()(fn)
    return srv
