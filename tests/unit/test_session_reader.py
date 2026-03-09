"""Tests for parse_session — Pi JSONL parsing."""

import json
from pathlib import Path


def _write_pi_messages(path: Path, messages: list[dict]) -> None:
    """Write Pi-format JSONL entries to a file."""
    with open(path, "a", encoding="utf-8") as f:
        for msg in messages:
            entry = {
                "type": "message",
                "id": msg.get("id", "test"),
                "parentId": None,
                "timestamp": "2026-03-06T00:00:00Z",
                "message": {
                    "role": msg["role"],
                    "content": [{"type": "text", "text": msg["text"]}],
                },
            }
            f.write(json.dumps(entry) + "\n")


def test_parses_user_and_assistant_messages(tmp_path):
    from clarvis.memory.session_reader import parse_session

    session_file = tmp_path / "session.jsonl"
    _write_pi_messages(
        session_file,
        [
            {"role": "user", "text": "hello", "id": "1"},
            {"role": "assistant", "text": "hi there", "id": "2"},
        ],
    )

    messages = parse_session(session_file)

    assert len(messages) == 2
    assert messages[0] == {"role": "user", "text": "hello"}
    assert messages[1] == {"role": "assistant", "text": "hi there"}


def test_skips_non_message_entries(tmp_path):
    from clarvis.memory.session_reader import parse_session

    session_file = tmp_path / "session.jsonl"
    with open(session_file, "w") as f:
        f.write(json.dumps({"type": "session", "id": "abc"}) + "\n")
        f.write(json.dumps({"type": "model_change", "id": "def"}) + "\n")
        f.write(
            json.dumps(
                {
                    "type": "message",
                    "id": "1",
                    "parentId": None,
                    "timestamp": "2026-03-06T00:00:00Z",
                    "message": {"role": "user", "content": [{"type": "text", "text": "real msg"}]},
                }
            )
            + "\n"
        )

    messages = parse_session(session_file)
    assert len(messages) == 1
    assert messages[0]["text"] == "real msg"


def test_skips_system_messages(tmp_path):
    from clarvis.memory.session_reader import parse_session

    session_file = tmp_path / "session.jsonl"
    with open(session_file, "w") as f:
        f.write(
            json.dumps(
                {
                    "type": "message",
                    "id": "1",
                    "message": {"role": "system", "content": [{"type": "text", "text": "system prompt"}]},
                }
            )
            + "\n"
        )
        f.write(
            json.dumps(
                {
                    "type": "message",
                    "id": "2",
                    "message": {"role": "user", "content": [{"type": "text", "text": "hello"}]},
                }
            )
            + "\n"
        )

    messages = parse_session(session_file)
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def test_missing_file_returns_empty(tmp_path):
    from clarvis.memory.session_reader import parse_session

    messages = parse_session(tmp_path / "nope.jsonl")
    assert messages == []


def test_handles_string_content_blocks(tmp_path):
    from clarvis.memory.session_reader import parse_session

    session_file = tmp_path / "session.jsonl"
    with open(session_file, "w") as f:
        f.write(
            json.dumps(
                {
                    "type": "message",
                    "id": "1",
                    "message": {"role": "user", "content": ["plain string content"]},
                }
            )
            + "\n"
        )

    messages = parse_session(session_file)
    assert len(messages) == 1
    assert messages[0]["text"] == "plain string content"
