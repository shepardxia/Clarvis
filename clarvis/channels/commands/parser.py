"""Command parser — keyword-based splitter for channel bot commands.

Produces the same flat dicts as the old Lark grammar, but handles
multi-word names naturally (no quoting required).  Comma-separates
values within ``name`` and ``org`` clauses.

Examples::

    register shepardxia name Shepard Xia, Shep org CS Lab
    → {"command": "register", "username": "shepardxia",
       "name": ["Shepard Xia", "Shep"], "org": ["CS Lab"]}

    unregister → {"command": "unregister"}
"""

import re
from typing import Any

COMMANDS = {
    "register",
    "unregister",
    "enable",
    "disable",
    "status",
    "addorg",
    "removeorg",
    "whois",
    "promote",
    "demote",
}

_TARGET_COMMANDS = {"addorg", "removeorg", "whois", "promote", "demote"}

_CLAUSE_KEYWORDS = {"name", "org"}


class ParseError(Exception):
    """Raised when command text doesn't match expected syntax."""


def _split_clauses(text: str) -> list[tuple[str, str]]:
    """Split text on clause keywords, returning (keyword, value) pairs.

    Uses word-boundary regex so 'name' inside a value won't split.
    """
    pattern = r"\b(" + "|".join(_CLAUSE_KEYWORDS) + r")\b"
    parts = re.split(pattern, text, flags=re.IGNORECASE)

    # parts alternates: [before, kw, value, kw, value, ...]
    clauses = []
    i = 1  # skip leading text (should be empty after username extraction)
    while i < len(parts) - 1:
        keyword = parts[i].lower()
        value = parts[i + 1].strip()
        clauses.append((keyword, value))
        i += 2
    return clauses


def _comma_split(text: str) -> list[str]:
    """Split on commas, strip whitespace, drop empties."""
    return [s.strip() for s in text.split(",") if s.strip()]


def parse(text: str) -> dict[str, Any]:
    """Parse a command string into a flat dict.

    Raises ``ParseError`` on invalid syntax.
    """
    text = text.strip()
    if not text:
        raise ParseError("Empty command")

    words = text.split()
    command = words[0].lower()

    if command not in COMMANDS:
        raise ParseError(f"Unknown command: {command}")

    # Simple commands — no arguments
    if command in {"unregister", "enable", "disable", "status"}:
        return {"command": command}

    # Target commands — rest of line is the target
    if command in _TARGET_COMMANDS:
        target = " ".join(words[1:]).strip()
        if not target:
            raise ParseError(f"Usage: !{command} <name>")
        return {"command": command, "target": target}

    # register <username> [name ...] [org ...]
    if len(words) < 2:
        raise ParseError("Usage: register <username> [name Name1, Name2] [org OrgName]")

    username = words[1]
    result: dict[str, Any] = {"command": "register", "username": username}

    # Everything after username is clause territory
    remainder = text[text.index(username) + len(username) :].strip()
    if not remainder:
        return result

    # Check remainder starts with a clause keyword
    first_word = remainder.split()[0].lower()
    if first_word not in _CLAUSE_KEYWORDS:
        raise ParseError(f"Unexpected '{first_word}' — expected 'name' or 'org' after username")

    for keyword, value in _split_clauses(remainder):
        if not value:
            raise ParseError(f"Empty '{keyword}' clause")
        result[keyword] = _comma_split(value)

    return result
