"""Tests for SessionReader — multi-source watermark JSONL reader."""

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


class TestSessionReader:
    def test_reads_new_messages(self, tmp_path):
        from clarvis.agent.memory.session_reader import SessionReader

        session_file = tmp_path / "session.jsonl"
        _write_pi_messages(
            session_file,
            [
                {"role": "user", "text": "hello", "id": "1"},
                {"role": "assistant", "text": "hi there", "id": "2"},
            ],
        )

        reader = SessionReader(
            sources={"clarvis": session_file},
            watermark_file=tmp_path / "watermarks.json",
        )
        pending = reader.read_pending()

        assert "clarvis" in pending
        assert len(pending["clarvis"]) == 2
        assert pending["clarvis"][0]["role"] == "user"
        assert pending["clarvis"][0]["text"] == "hello"

    def test_watermark_skips_already_read(self, tmp_path):
        from clarvis.agent.memory.session_reader import SessionReader

        session_file = tmp_path / "session.jsonl"
        _write_pi_messages(
            session_file,
            [
                {"role": "user", "text": "first", "id": "1"},
            ],
        )

        reader = SessionReader(
            sources={"clarvis": session_file},
            watermark_file=tmp_path / "watermarks.json",
        )
        reader.read_pending()
        reader.advance("clarvis")

        # Add more messages
        _write_pi_messages(
            session_file,
            [
                {"role": "user", "text": "second", "id": "2"},
            ],
        )

        pending = reader.read_pending()
        assert len(pending["clarvis"]) == 1
        assert pending["clarvis"][0]["text"] == "second"

    def test_multiple_sources(self, tmp_path):
        from clarvis.agent.memory.session_reader import SessionReader

        clarvis_file = tmp_path / "clarvis.jsonl"
        factoria_file = tmp_path / "factoria.jsonl"

        _write_pi_messages(
            clarvis_file,
            [
                {"role": "user", "text": "voice msg", "id": "1"},
            ],
        )
        _write_pi_messages(
            factoria_file,
            [
                {"role": "user", "text": "discord msg", "id": "2"},
            ],
        )

        reader = SessionReader(
            sources={"clarvis": clarvis_file, "factoria": factoria_file},
            watermark_file=tmp_path / "watermarks.json",
        )
        pending = reader.read_pending()

        assert len(pending["clarvis"]) == 1
        assert len(pending["factoria"]) == 1

    def test_skips_non_message_entries(self, tmp_path):
        from clarvis.agent.memory.session_reader import SessionReader

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

        reader = SessionReader(
            sources={"test": session_file},
            watermark_file=tmp_path / "watermarks.json",
        )
        pending = reader.read_pending()
        assert len(pending["test"]) == 1

    def test_missing_source_file(self, tmp_path):
        from clarvis.agent.memory.session_reader import SessionReader

        reader = SessionReader(
            sources={"missing": tmp_path / "nope.jsonl"},
            watermark_file=tmp_path / "watermarks.json",
        )
        pending = reader.read_pending()
        assert pending["missing"] == []

    def test_advance_persists(self, tmp_path):
        from clarvis.agent.memory.session_reader import SessionReader

        session_file = tmp_path / "session.jsonl"
        _write_pi_messages(
            session_file,
            [
                {"role": "user", "text": "msg", "id": "1"},
            ],
        )

        reader1 = SessionReader(
            sources={"s": session_file},
            watermark_file=tmp_path / "watermarks.json",
        )
        reader1.read_pending()
        reader1.advance("s")

        # New reader instance loads persisted watermarks
        reader2 = SessionReader(
            sources={"s": session_file},
            watermark_file=tmp_path / "watermarks.json",
        )
        pending = reader2.read_pending()
        assert pending["s"] == []
