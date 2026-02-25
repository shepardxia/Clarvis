"""Tests for the channel command system — parser, executor, roles & permissions."""

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
    """Minimal ChannelState stub."""

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
    """Fresh registry with one admin and one regular user."""
    reg = UserRegistry(path=tmp_path / "registry.json", admin_user_ids=[ADMIN_UID])
    reg.register(
        username="adminuser",
        names=["Admin"],
        channel=CHANNEL,
        channel_user_id=ADMIN_UID,
    )
    reg.register(
        username="normaluser",
        names=["Normal"],
        channel=CHANNEL,
        channel_user_id=USER_UID,
    )
    return reg


@pytest.fixture
def state():
    return FakeState()


@pytest.fixture
def executor(registry, state):
    return CommandExecutor(registry, state)


# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParser:
    """Parser: new target commands parse correctly."""

    @pytest.mark.parametrize("cmd", ["addorg", "removeorg", "whois", "promote", "demote"])
    def test_target_commands_parse(self, cmd):
        result = parse(f"{cmd} SomeName")
        assert result["command"] == cmd
        assert result["target"] == "SomeName"

    def test_target_with_spaces(self):
        result = parse("whois John Doe")
        assert result["target"] == "John Doe"

    @pytest.mark.parametrize("cmd", ["addorg", "removeorg", "whois", "promote", "demote"])
    def test_target_missing_raises(self, cmd):
        with pytest.raises(ParseError, match="Usage"):
            parse(cmd)

    def test_existing_commands_still_work(self):
        assert parse("status") == {"command": "status"}
        assert parse("unregister") == {"command": "unregister"}
        assert parse("enable") == {"command": "enable"}


# ---------------------------------------------------------------------------
# Registry role tests
# ---------------------------------------------------------------------------


class TestRegistryRoles:
    """Registry: role assignment, migration, get/set."""

    def test_admin_auto_assigned(self, registry):
        role = registry.get_role(CHANNEL, ADMIN_UID)
        assert role == "admin"

    def test_user_auto_assigned(self, registry):
        role = registry.get_role(CHANNEL, USER_UID)
        assert role == "user"

    def test_unregistered_returns_none(self, registry):
        assert registry.get_role(CHANNEL, UNREGISTERED_UID) is None

    def test_set_role(self, registry):
        assert registry.set_role("normaluser", "admin")
        assert registry.get_role(CHANNEL, USER_UID) == "admin"

    def test_set_role_not_found(self, registry):
        assert not registry.set_role("ghost", "admin")

    def test_migration_on_load(self, tmp_path):
        """Users without role field get one on load."""
        from clarvis.core.persistence import json_save_atomic

        path = tmp_path / "reg.json"
        json_save_atomic(
            path,
            {
                "users": {
                    "alice": {
                        "names": ["Alice"],
                        "channels": {"discord": {"user_id": "111"}},
                        # no "role" key
                    }
                }
            },
        )
        reg = UserRegistry(path=path, admin_user_ids=["111"])
        assert reg.get_role("discord", "111") == "admin"

    def test_migration_preserves_existing_role(self, tmp_path):
        """Existing role field is not overwritten."""
        from clarvis.core.persistence import json_save_atomic

        path = tmp_path / "reg.json"
        json_save_atomic(
            path,
            {
                "users": {
                    "bob": {
                        "names": ["Bob"],
                        "role": "user",
                        "channels": {"discord": {"user_id": "111"}},
                    }
                }
            },
        )
        # 111 is in admin list, but existing role should be preserved
        reg = UserRegistry(path=path, admin_user_ids=["111"])
        assert reg.get_role("discord", "111") == "user"

    def test_register_new_user_gets_role(self, tmp_path):
        """Newly registered user auto-gets role based on admin_user_ids."""
        reg = UserRegistry(path=tmp_path / "reg.json", admin_user_ids=["333"])
        reg.register(
            username="newadmin",
            names=["New"],
            channel="discord",
            channel_user_id="333",
        )
        assert reg.get_role("discord", "333") == "admin"


# ---------------------------------------------------------------------------
# Permission tests
# ---------------------------------------------------------------------------


class TestPermissions:
    """Executor: admin-only commands gated by role."""

    @pytest.mark.parametrize("cmd", ["enable", "disable"])
    def test_admin_allowed(self, executor, cmd):
        result = executor.execute({"command": cmd}, ADMIN_UID, CHAT_ID, CHANNEL)
        assert "Permission denied" not in result

    @pytest.mark.parametrize("cmd", ["enable", "disable", "addorg", "removeorg", "promote", "demote"])
    def test_user_denied(self, executor, cmd):
        parsed = {"command": cmd}
        if cmd in {"addorg", "removeorg", "promote", "demote"}:
            parsed["target"] = "something"
        result = executor.execute(parsed, USER_UID, CHAT_ID, CHANNEL)
        assert result == "Permission denied — admin only."

    @pytest.mark.parametrize("cmd", ["enable", "disable", "addorg", "removeorg", "promote", "demote"])
    def test_unregistered_denied(self, executor, cmd):
        parsed = {"command": cmd}
        if cmd in {"addorg", "removeorg", "promote", "demote"}:
            parsed["target"] = "something"
        result = executor.execute(parsed, UNREGISTERED_UID, CHAT_ID, CHANNEL)
        assert result == "Permission denied — admin only."

    def test_non_admin_commands_allowed_for_all(self, executor):
        """register, unregister, status, whois don't need admin."""
        result = executor.execute(
            {"command": "status"},
            USER_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert "Permission denied" not in result


# ---------------------------------------------------------------------------
# Executor handler tests
# ---------------------------------------------------------------------------


class TestExecutorHandlers:
    """Executor: new command handlers — happy and error paths."""

    def test_addorg(self, executor):
        result = executor.execute(
            {"command": "addorg", "target": "NewLab"},
            ADMIN_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert result == "Added org: NewLab"

    def test_addorg_duplicate(self, executor):
        executor.execute(
            {"command": "addorg", "target": "Lab"},
            ADMIN_UID,
            CHAT_ID,
            CHANNEL,
        )
        result = executor.execute(
            {"command": "addorg", "target": "Lab"},
            ADMIN_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert result == "Org already exists."

    def test_removeorg(self, executor, registry):
        registry.add_org("OldLab")
        result = executor.execute(
            {"command": "removeorg", "target": "OldLab"},
            ADMIN_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert result == "Removed org: OldLab"

    def test_removeorg_not_found(self, executor):
        result = executor.execute(
            {"command": "removeorg", "target": "Ghost"},
            ADMIN_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert result == "Org not found."

    def test_whois_found(self, executor):
        result = executor.execute(
            {"command": "whois", "target": "normaluser"},
            USER_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert "normaluser" in result
        assert "Normal" in result

    def test_whois_by_alias_shows_username(self, executor):
        """Searching by alias should display the registry username, not the search term."""
        result = executor.execute(
            {"command": "whois", "target": "Normal"},
            USER_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert "**normaluser**" in result

    def test_whois_not_found(self, executor):
        result = executor.execute(
            {"command": "whois", "target": "ghost"},
            USER_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert result == "Not found: ghost"

    def test_whois_shows_admin_tag(self, executor):
        result = executor.execute(
            {"command": "whois", "target": "adminuser"},
            USER_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert "[admin]" in result

    def test_promote(self, executor, registry):
        result = executor.execute(
            {"command": "promote", "target": "normaluser"},
            ADMIN_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert "Promoted" in result
        assert registry.get_role(CHANNEL, USER_UID) == "admin"

    def test_promote_not_found(self, executor):
        result = executor.execute(
            {"command": "promote", "target": "ghost"},
            ADMIN_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert result == "User not found."

    def test_demote(self, executor, registry):
        # First promote, then demote
        registry.set_role("normaluser", "admin")
        result = executor.execute(
            {"command": "demote", "target": "normaluser"},
            ADMIN_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert "Demoted" in result
        assert registry.get_role(CHANNEL, USER_UID) == "user"

    def test_status_shows_admin_marker(self, executor):
        result = executor.execute(
            {"command": "status"},
            ADMIN_UID,
            CHAT_ID,
            CHANNEL,
        )
        assert "[admin]" in result
        assert "adminuser" in result


# ---------------------------------------------------------------------------
# Context enrichment tests
# ---------------------------------------------------------------------------


class TestContextRoleTag:
    """Context: [admin] tag in identity string."""

    def _make_msg(self, sender_id):
        """Create a minimal InboundMessage-like object."""
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

    def test_regular_user_no_tag(self, registry):
        msg = self._make_msg(USER_UID)
        prefix = build_context_prefix(msg, registry)
        assert "[admin]" not in prefix
        assert "[user]" not in prefix

    def test_unregistered_no_tag(self, registry):
        msg = self._make_msg(UNREGISTERED_UID)
        prefix = build_context_prefix(msg, registry)
        assert "[admin]" not in prefix
