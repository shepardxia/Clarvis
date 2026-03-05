"""Channel command system — role assignment, migration, permission gates, edge cases.

Trivial parse/CRUD tests removed. Keeps: role logic, migration, permission
gating, duplicate detection, alias lookup, admin tag decoration.
"""

import pytest

from clarvis.channels.commands.executor import CommandExecutor
from clarvis.channels.commands.parser import ParseError, parse
from clarvis.channels.context import build_context_prefix
from clarvis.channels.registry import UserRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

ADMIN_UID = "111"
USER_UID = "222"
UNREGISTERED_UID = "999"
CHANNEL = "discord"
CHAT_ID = "general"


class FakeState:
    def __init__(self):
        self._chats: dict[str, set[str]] = {}

    def enable_chat(self, channel: str, chat_id: str) -> None:
        self._chats.setdefault(channel, set()).add(chat_id)

    def disable_chat(self, channel: str, chat_id: str) -> None:
        self._chats.get(channel, set()).discard(chat_id)

    def enabled_chats(self, channel: str) -> list[str]:
        return sorted(self._chats.get(channel, set()))


@pytest.fixture
def registry(tmp_path):
    reg = UserRegistry(path=tmp_path / "registry.json", admin_user_ids=[ADMIN_UID])
    reg.register(username="adminuser", names=["Admin"], channel=CHANNEL, channel_user_id=ADMIN_UID)
    reg.register(username="normaluser", names=["Normal"], channel=CHANNEL, channel_user_id=USER_UID)
    return reg


@pytest.fixture
def state():
    return FakeState()


@pytest.fixture
def executor(registry, state):
    return CommandExecutor(registry, state)


# ---------------------------------------------------------------------------
# Parser — only edge cases
# ---------------------------------------------------------------------------


class TestParser:
    @pytest.mark.parametrize("cmd", ["addorg", "removeorg", "whois", "promote", "demote"])
    def test_target_missing_raises(self, cmd):
        with pytest.raises(ParseError, match="Usage"):
            parse(cmd)


# ---------------------------------------------------------------------------
# Registry roles — assignment & migration
# ---------------------------------------------------------------------------


class TestRegistryRoles:
    def test_admin_auto_assigned(self, registry):
        assert registry.get_role(CHANNEL, ADMIN_UID) == "admin"

    def test_migration_on_load(self, tmp_path):
        """Users without role field get one on load."""
        from clarvis.core.persistence import json_save_atomic

        path = tmp_path / "reg.json"
        json_save_atomic(
            path,
            {"users": {"alice": {"names": ["Alice"], "channels": {"discord": {"user_id": "111"}}}}},
        )
        reg = UserRegistry(path=path, admin_user_ids=["111"])
        assert reg.get_role("discord", "111") == "admin"

    def test_migration_preserves_existing_role(self, tmp_path):
        """Existing role field is not overwritten by admin_user_ids."""
        from clarvis.core.persistence import json_save_atomic

        path = tmp_path / "reg.json"
        json_save_atomic(
            path,
            {"users": {"bob": {"names": ["Bob"], "role": "user", "channels": {"discord": {"user_id": "111"}}}}},
        )
        reg = UserRegistry(path=path, admin_user_ids=["111"])
        assert reg.get_role("discord", "111") == "user"


# ---------------------------------------------------------------------------
# Permissions — admin-only commands gated by role
# ---------------------------------------------------------------------------


class TestPermissions:
    @pytest.mark.parametrize("cmd", ["enable", "disable", "addorg", "removeorg", "promote", "demote"])
    def test_user_denied(self, executor, cmd):
        parsed = {"command": cmd}
        if cmd in {"addorg", "removeorg", "promote", "demote"}:
            parsed["target"] = "something"
        result = executor.execute(parsed, USER_UID, CHAT_ID, CHANNEL)
        assert result == "Permission denied — admin only."


# ---------------------------------------------------------------------------
# Executor handlers — edge cases & meaningful logic
# ---------------------------------------------------------------------------


class TestExecutorHandlers:
    def test_addorg_duplicate(self, executor):
        executor.execute({"command": "addorg", "target": "Lab"}, ADMIN_UID, CHAT_ID, CHANNEL)
        result = executor.execute({"command": "addorg", "target": "Lab"}, ADMIN_UID, CHAT_ID, CHANNEL)
        assert result == "Org already exists."

    def test_whois_by_alias_shows_username(self, executor):
        """Searching by alias should display the registry username."""
        result = executor.execute({"command": "whois", "target": "Normal"}, USER_UID, CHAT_ID, CHANNEL)
        assert "**normaluser**" in result

    def test_whois_shows_admin_tag(self, executor):
        result = executor.execute({"command": "whois", "target": "adminuser"}, USER_UID, CHAT_ID, CHANNEL)
        assert "[admin]" in result


# ---------------------------------------------------------------------------
# Context enrichment
# ---------------------------------------------------------------------------


class TestContextRoleTag:
    def _make_msg(self, sender_id):
        from datetime import datetime, timezone

        class FakeMsg:
            channel = CHANNEL
            timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
            metadata = {"author_username": "testuser"}

        msg = FakeMsg()
        msg.sender_id = sender_id
        return msg

    def test_admin_gets_tag(self, registry):
        msg = self._make_msg(ADMIN_UID)
        prefix = build_context_prefix(msg, registry)
        assert "[admin]" in prefix
