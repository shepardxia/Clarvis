"""Spotify DSL MCP sub-server — mounted onto the main Clarvis server.

Single tool that accepts DSL command strings via the clautify package.
Formats raw responses as concise text for LLM consumption.
"""

import logging
import re
from contextlib import asynccontextmanager
from typing import Annotated, Any, List

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
            from .widget.config import get_config

            session.max_volume = get_config().spotify.max_volume / 100
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


def _ms_to_timestamp(ms: Any) -> str:
    """Convert milliseconds (int or str) to M:SS format."""
    try:
        total_s = int(ms) // 1000
    except (TypeError, ValueError):
        return "?"
    m, s = divmod(total_s, 60)
    return f"{m}:{s:02d}"


def _get_cache(session):
    """Access the executor's name cache for reverse URI lookups."""
    try:
        return session._executor._cache
    except AttributeError:
        return None


# --- Query formatters ---


def _fmt_search(result: dict, session) -> str:
    type_ = result.get("type", "tracks")
    data = result.get("data")

    if not isinstance(data, list) or not data:
        return "No results."

    if type_ == "artists":
        # data is already a flat items list (extracted by executor)
        lines = []
        for item in data:
            try:
                name = item["data"]["profile"]["name"]
                lines.append(name)
            except (KeyError, TypeError):
                continue
        return "\n".join(lines) if lines else "No results."

    # tracks, albums, playlists — data is already the extracted items list
    lines = []
    for item in data:
        try:
            d = item.get("item", {}).get("data", {}) if type_ == "tracks" else item.get("data", {})
            name = d.get("name", "?")

            if type_ == "tracks":
                artists = d.get("artists", {}).get("items", [])
                artist = artists[0]["profile"]["name"] if artists else "?"
                album = d.get("albumOfTrack", {}).get("name", "")
                line = f'"{name}" - {artist}'
                if album:
                    line += f" ({album})"
            elif type_ == "albums":
                artists = d.get("artists", {}).get("items", [])
                artist = artists[0]["profile"]["name"] if artists else "?"
                line = f'"{name}" - {artist}'
            elif type_ == "playlists":
                owner = d.get("ownerV2", {}).get("data", {}).get("name", "?")
                count = (d.get("content") or {}).get("totalCount")
                line = f'"{name}" - {owner}'
                if count:
                    line += f" ({count} tracks)"
            else:
                line = name

            lines.append(line)
        except (KeyError, TypeError, IndexError):
            continue
    return "\n".join(lines) if lines else "No results."


def _fmt_now_playing(result: dict, session) -> str:
    state = result.get("data")
    if state is None:
        return "Nothing playing."

    cache = _get_cache(session)

    # Handle PlayerState dataclass
    if hasattr(state, "track"):
        track = state.track
        if not track:
            return "Nothing playing."
        m = track.metadata
        title = m.title if m else "?"
        album = m.album_title if m else ""
        # Try reverse-lookup for artist name
        artist = None
        if m and m.artist_uri and cache:
            artist = cache.name_for_uri(m.artist_uri)

        line = f'"{title}"'
        if artist:
            line += f" by {artist}"
        if album:
            line += f" ({album})"

        if state.is_paused is True or state.is_playing is False:
            return f"{line}\npaused"

        pos = _ms_to_timestamp(state.position_as_of_timestamp)
        dur = _ms_to_timestamp(state.duration)
        mode_parts = []
        if state.options:
            if state.options.shuffling_context:
                mode_parts.append("shuffle")
            if state.options.repeating_context:
                mode_parts.append("repeat")

        status_line = f"{pos} / {dur}"
        if mode_parts:
            status_line += ", " + ", ".join(mode_parts)
        return f"{line}\n{status_line}"

    return str(state)


def _fmt_devices(result: dict, session) -> str:
    data = result.get("data")
    if data is None:
        return "No devices."

    lines = []
    active_id = None

    if hasattr(data, "devices"):
        active_id = data.active_device_id
        devices = data.devices
        for dev_id, dev in devices.items():
            parts = [dev.name]
            parts.append(f"({dev.device_type.title()}")
            if dev_id == active_id:
                parts[-1] += ", currently used"
            vol_pct = round(dev.volume / 65535 * 100) if dev.volume is not None else "?"
            parts[-1] += f", vol: {vol_pct}%)"
            lines.append(" ".join(parts))
    elif isinstance(data, dict):
        for dev_id, dev in data.items():
            name = dev.get("name", dev_id) if isinstance(dev, dict) else str(dev)
            lines.append(name)

    return "\n".join(lines) if lines else "No devices."


def _fmt_queue_or_history(result: dict, session) -> str:
    data = result.get("data")
    if not data:
        return "Empty."
    if not isinstance(data, list):
        data = [data] if data else []

    cap = result.get("limit", 10)
    cache = _get_cache(session)
    lines = []
    unknown_count = 0

    for track in data[:cap]:
        if hasattr(track, "metadata"):
            m = track.metadata
            title = m.title if m else None
            if title:
                album = m.album_title or ""
                artist = None
                if m.artist_uri and cache:
                    artist = cache.name_for_uri(m.artist_uri)
                line = f'"{title}"'
                if artist:
                    line += f" - {artist}"
                if album:
                    line += f" ({album})"
                lines.append(line)
            elif track.uri and cache:
                # Fallback: resolve track URI from cache
                name = cache.name_for_uri(track.uri)
                if name:
                    lines.append(f'"{name}"')
                else:
                    unknown_count += 1
            else:
                unknown_count += 1
        elif isinstance(track, dict):
            name = track.get("name") or track.get("title")
            if not name and cache:
                uri = track.get("uri")
                if uri:
                    name = cache.name_for_uri(uri)
            if name:
                lines.append(f'"{name}"')
            else:
                unknown_count += 1
        else:
            unknown_count += 1

    if unknown_count > 0:
        lines.append(f"...and {unknown_count} untitled tracks")

    remaining = len(data) - cap
    if remaining > 0:
        lines.append(f"...and {remaining} more in queue")

    return "\n".join(lines) if lines else "Empty."


def _fmt_recommend(result: dict, session) -> str:
    data = result.get("data")
    if not data:
        return "No recommendations."

    tracks = data.get("recommendedTracks", []) if isinstance(data, dict) else []
    lines = []
    for t in tracks:
        try:
            name = t["name"]
            artists = t.get("artists", [])
            artist = artists[0]["name"] if artists else "?"
            album = t.get("album", {}).get("name", "")
            line = f'"{name}" - {artist}'
            if album:
                line += f" ({album})"
            lines.append(line)
        except (KeyError, TypeError, IndexError):
            continue
    return "\n".join(lines) if lines else "No recommendations."


def _fmt_library(result: dict, session) -> str:
    data = result.get("data")
    if not data:
        return "Library empty."

    try:
        items = data["data"]["me"]["libraryV3"]["items"]
    except (KeyError, TypeError):
        return "Library empty."

    # Get current user name for my vs saved playlists
    user_name = None
    try:
        for item in items:
            owner = item.get("item", {}).get("data", {}).get("ownerV2", {}).get("data", {})
            if owner.get("uri", "").startswith("spotify:user:"):
                user_name = owner.get("name")
                break
    except (KeyError, TypeError):
        pass

    my_playlists: List[str] = []
    saved_playlists: List[str] = []
    albums: List[str] = []
    following: List[str] = []

    for item in items:
        try:
            item_data = item.get("item", {}).get("data", {})
            typename = item_data.get("__typename", "")
            name = item_data.get("name", "?")

            # Skip podcasts, audiobooks, episodes
            if any(kw in typename.lower() for kw in ("podcast", "show", "audiobook", "episode")):
                continue

            if "PseudoPlaylist" in typename:
                # Built-in collections like Liked Songs, Your Episodes
                if "episode" in name.lower():
                    continue
                count = item_data.get("count", "?")
                my_playlists.append(f"{name} ({count} tracks)")
            elif "Playlist" in typename:
                owner = item_data.get("ownerV2", {}).get("data", {}).get("name", "?")
                # Count not directly available in library response
                if user_name and owner == user_name:
                    my_playlists.append(f'"{name}"')
                else:
                    saved_playlists.append(f'"{name}" by {owner}')
            elif "Album" in typename:
                artist = "?"
                try:
                    artist = item_data["artists"]["items"][0]["profile"]["name"]
                except (KeyError, TypeError, IndexError):
                    pass
                albums.append(f'"{name}" - {artist}')
            elif "Artist" in typename:
                artist_name = item_data.get("profile", {}).get("name") or name
                following.append(artist_name)
        except (KeyError, TypeError):
            continue

    sections = []
    if my_playlists:
        sections.append("My Playlists:\n" + "\n".join(f"  {p}" for p in my_playlists[:10]))
    if albums:
        sections.append("Albums:\n" + "\n".join(f"  {a}" for a in albums[:10]))
    if following:
        sections.append("Following:\n" + "\n".join(f"  {a}" for a in following[:10]))
    if saved_playlists:
        sections.append("Saved Playlists:\n" + "\n".join(f"  {p}" for p in saved_playlists[:10]))

    return "\n\n".join(sections) if sections else "Library empty."


def _fmt_info(result: dict, session) -> str:
    target = result.get("target", "")
    data = result.get("data")
    if not data:
        return "No info available."

    # Parse kind from URI structure (spotify:artist:xxx → "artist")
    parts = target.split(":")
    kind = parts[1] if len(parts) >= 3 else "track"

    try:
        if kind == "artist":
            return _fmt_info_artist(data)
        elif kind == "album":
            return _fmt_info_album(data)
        elif kind == "playlist":
            return _fmt_info_playlist(data)
        else:
            return _fmt_info_track(data)
    except (KeyError, TypeError, IndexError):
        return str(data)[:2000]


def _fmt_info_artist(data: dict) -> str:
    artist = data.get("data", {}).get("artistUnion", {})
    profile = artist.get("profile", {})
    name = profile.get("name", "?")
    bio = profile.get("biography", {}).get("text", "")
    stats = artist.get("stats", {})
    listeners = stats.get("monthlyListeners", 0)
    rank = stats.get("worldRank")

    lines = [name]
    stat_parts = []
    if listeners:
        stat_parts.append(f"{listeners:,} monthly listeners")
    if rank:
        stat_parts.append(f"#{rank} worldwide")
    if stat_parts:
        lines.append(", ".join(stat_parts))

    if bio:
        bio = re.sub(r"<[^>]+>", "", bio)  # strip HTML tags
        # Take first paragraph only
        first_para = bio.split("\n")[0].split("\r")[0].strip()
        if len(first_para) > 300:
            first_para = first_para[:297] + "..."
        if first_para:
            lines.append("")
            lines.append(first_para)

    # Top tracks
    top_tracks = artist.get("discography", {}).get("topTracks", {}).get("items", [])
    if top_tracks:
        names = []
        for t in top_tracks[:5]:
            track = t.get("track", {})
            n = track.get("name")
            if n:
                names.append(f'"{n}"')
        if names:
            lines.append("")
            lines.append("Top tracks:")
            lines.append(", ".join(names))

    # Albums
    album_items = artist.get("discography", {}).get("albums", {}).get("items", [])
    if album_items:
        album_names = []
        for a in album_items[:10]:
            releases = a.get("releases", {}).get("items", [])
            if releases:
                name_a = releases[0].get("name")
                year = releases[0].get("date", {}).get("year", "")
                if name_a:
                    album_names.append(f'"{name_a}" ({year})' if year else f'"{name_a}"')
        if album_names:
            lines.append("")
            lines.append("Albums:")
            lines.append(", ".join(album_names))

    # Related artists
    related = artist.get("relatedContent", {}).get("relatedArtists", {}).get("items", [])
    if related:
        rel_names = [r.get("profile", {}).get("name") for r in related[:10]]
        rel_names = [n for n in rel_names if n]
        if rel_names:
            lines.append("")
            lines.append("Related artists:")
            lines.append(", ".join(rel_names))

    return "\n".join(lines)


def _fmt_info_album(data: dict) -> str:
    album = data.get("data", {}).get("albumUnion", {})
    name = album.get("name", "?")
    artists = album.get("artists", {}).get("items", [])
    artist = artists[0].get("profile", {}).get("name", "?") if artists else "?"
    date = album.get("date", {})
    year = date.get("year") or (date.get("isoString", "")[:4] if date.get("isoString") else "")
    label = album.get("label", "")

    header_parts = [f'"{name}" by {artist}']
    meta = []
    if year:
        meta.append(str(year))
    if label:
        meta.append(label)
    if meta:
        header_parts.append(f"({', '.join(meta)})")

    tracks = (album.get("tracksV2") or album.get("tracks") or {}).get("items", [])
    track_names = []
    for t in tracks:
        track = t.get("track", {})
        n = track.get("name")
        if n:
            track_names.append(f'"{n}"')

    lines = [" ".join(header_parts)]
    if track_names:
        lines.append(", ".join(track_names))
    return "\n".join(lines)


def _fmt_info_playlist(data: dict) -> str:
    pl = data.get("data", {}).get("playlistV2", {})
    name = pl.get("name", "?")
    owner = pl.get("ownerV2", {}).get("data", {}).get("name", "?")
    total = pl.get("content", {}).get("totalCount", "?")

    lines = [f'"{name}" by {owner} - {total} tracks']

    items = pl.get("content", {}).get("items", [])
    for item in items[:20]:
        try:
            track_data = item.get("itemV2", {}).get("data", {})
            track_name = track_data.get("name", "?")
            artists = track_data.get("artists", {}).get("items", [])
            artist = artists[0].get("profile", {}).get("name", "?") if artists else "?"
            lines.append(f'"{track_name}" - {artist}')
        except (KeyError, TypeError, IndexError):
            continue

    if len(items) > 20:
        lines.append(f"...and {len(items) - 20} more")

    return "\n".join(lines)


def _fmt_info_track(data: dict) -> str:
    track = data.get("data", {}).get("trackUnion", {})
    name = track.get("name", "?")
    artists = track.get("firstArtist", {}).get("items", [])
    artist = artists[0].get("profile", {}).get("name", "?") if artists else "?"
    album = track.get("albumOfTrack", {}).get("name", "")
    duration = track.get("duration", {}).get("totalMilliseconds")
    playcount = track.get("playcount")

    line = f'"{name}" - {artist}'
    if album:
        line += f" ({album})"

    parts = [line]
    meta = []
    if duration:
        meta.append(_ms_to_timestamp(duration))
    if playcount:
        try:
            meta.append(f"{int(playcount):,} plays")
        except (ValueError, TypeError):
            pass
    if meta:
        parts.append(", ".join(meta))

    return "\n".join(parts)


# --- Action formatters ---


def _fmt_action(result: dict, session=None) -> str:
    action = result.get("action", "")
    target = result.get("target", "")
    kind = result.get("kind", "")
    # Resolve URI targets to names via cache
    if target and target.startswith("spotify:") and session:
        cache = _get_cache(session)
        if cache:
            target = cache.name_for_uri(target) or target

    if action == "pause":
        return "Paused"
    elif action == "resume":
        return "Resumed"
    elif action == "skip":
        n = result.get("n", 1)
        if n == 1:
            return "Skipped"
        elif n == -1:
            return "Skipped back"
        elif n > 0:
            return f"Skipped {n} tracks"
        else:
            return f"Skipped back {abs(n)} tracks"
    elif action == "seek":
        pos = result.get("position_ms")
        return f"Seeked to {_ms_to_timestamp(pos)}" if pos else "Seeked"
    elif action == "play":
        if kind in ("album", "playlist"):
            return f"Playing {kind} {target}"
        return f"Playing {target}"
    elif action == "queue":
        return f"Added {target} to queue"
    elif action == "set":
        parts = []
        if "volume" in result:
            parts.append(f"Volume set to {int(result['volume'])}%")
        if "volume_rel" in result:
            v = result["volume_rel"]
            parts.append(f"Volume {'+' if v > 0 else ''}{v}%")
        if "mode" in result:
            mode = result["mode"]
            if mode == "shuffle":
                parts.append("Shuffle on")
            elif mode == "repeat":
                parts.append("Repeat on")
            else:
                parts.append("Normal playback")
        if "device" in result:
            parts.append(f"Playing on {result['device']}")
        return ", ".join(parts) if parts else "OK"
    elif action in ("like", "unlike", "follow", "unfollow", "save", "unsave"):
        return f"{action.capitalize()}d {target}"
    elif action == "playlist_create":
        return f'Created playlist "{result.get("name", target)}"'
    elif action == "playlist_delete":
        return f"Deleted playlist {target}"
    elif action == "playlist_add":
        return "Added to playlist"
    elif action == "playlist_remove":
        return "Removed from playlist"

    return "OK"


# --- Main formatter ---


def _format_result(result: dict, session) -> str:
    """Format a clautify DSL result as concise text for LLM consumption."""
    if not isinstance(result, dict):
        return str(result)

    if "error" in result:
        return result["error"]

    query = result.get("query")
    action = result.get("action")

    try:
        if query:
            if query == "search":
                return _fmt_search(result, session)
            elif query == "now_playing":
                return _fmt_now_playing(result, session)
            elif query == "get_devices":
                return _fmt_devices(result, session)
            elif query in ("get_queue", "history"):
                return _fmt_queue_or_history(result, session)
            elif query == "recommend":
                return _fmt_recommend(result, session)
            elif query == "library":
                return _fmt_library(result, session)
            elif query == "info":
                return _fmt_info(result, session)
        elif action:
            return _fmt_action(result, session)
    except Exception:
        logger.warning("Formatter error for %s", query or action, exc_info=True)

    # Fallback: return raw result truncated
    raw = str(result)
    if len(raw) > 2000:
        return raw[:2000] + "... (truncated)"
    return raw


# --- Tool ---


async def spotify(
    command: Annotated[
        str,
        Field(description='Command string, e.g. \'play "jazz" volume 70 mode shuffle on "Den"\''),
    ],
    ctx: Context = None,
) -> str:
    """Execute a Spotify command using natural command strings.

    Quoted strings refer to names from previous search results (search first, then act).
    Modifiers compose in a single call. Examples:

        search "radiohead" tracks limit 5
        search "radiohead" "tool" "deftones" tracks
        now playing
        play track "Creep"
        play album "OK Computer"
        play playlist "Rages Cupped" mode shuffle
        queue "Karma Police"
        skip 3
        volume 50
        volume +10
        get devices
        library playlists
        info "Radiohead"
        recommend 5 for "Rages Cupped"

    ACTIONS: play [track|album|playlist] "name" [in "playlist"], pause, resume,
    skip [N], seek <ms>, queue "name", like/unlike "name", follow/unfollow "name",
    save/unsave "name", add "name" to "playlist", remove "name" from "playlist",
    create playlist "name", delete playlist "name".

    QUERIES: search "query"+ [tracks|artists|albums|playlists],
    now playing, get queue, get devices,
    library [playlists|artists|albums|tracks], info "name", history,
    recommend N for "playlist name".

    COMPOSABLE MODIFIERS (chain onto actions, or standalone):
    volume N (0-100, capped at configured max), volume +N/-N (relative),
    mode shuffle|repeat|normal, on "device name" (or: device "name").
    Query-only modifiers: limit N, offset N.

    IMPORTANT: Names in quotes are resolved from prior search/query results.
    You must search first to discover tracks/artists/albums, then reference
    them by name in subsequent commands. This is by design — always search
    before play, queue, info, or any name-based command. Search accepts
    multiple quoted terms to batch-populate the cache in one call.
    """
    session = ctx.fastmcp._lifespan_result["get_session"]()

    try:
        result = session.run(command)
    except Exception as e:
        result = {"error": str(e)}

    return _format_result(result, session)


# --- Sub-server factory ---

_TOOLS = [spotify]


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

    srv = FastMCP("spotify", lifespan=session_lifespan)
    for fn in _TOOLS:
        srv.tool()(fn)
    return srv
