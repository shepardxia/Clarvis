"""Cross-channel command parser — keyword-based registration and chat control.

Entry point: ``run()`` — normalizes punctuation, parses via keyword splitter,
and executes against registry/channel state.

Returns response string on command, ``None`` if not a command (fall through).
"""

import logging
from typing import TYPE_CHECKING

from .executor import CommandExecutor
from .parser import COMMANDS, ParseError, parse

if TYPE_CHECKING:
    from ..registry import UserRegistry
    from ..state import ChannelState

logger = logging.getLogger(__name__)

# Chinese punctuation → ASCII equivalents
_PUNCT_MAP = str.maketrans(
    {
        "\uff0c": ",",  # ，→ ,
        "\u201c": '"',  # " → "
        "\u201d": '"',  # " → "
        "\u2018": "'",  # ' → '
        "\u2019": "'",  # ' → '
    }
)


def _help_message() -> str:
    """Help text listing available commands."""
    return (
        "**可用命令** (需要加前缀 `!`):\n\n"
        "**注册 Register:**\n"
        "  `!register <用户名> name <名字> org <组织>`\n"
        "  多个名字/组织用逗号分隔\n"
        "  例 / Example: `!register Zhong name 老钟, Simon org SRTP, Torque`\n\n"
        "**其他 Other:**\n"
        "  `!unregister` — 取消注册\n"
        "  `!enable` / `!disable` — 开启/关闭本频道下的聊天\n"
        "  `!status` — 查看已注册用户、组织和聊天"
    )


def run(
    content: str,
    sender_id: str,
    chat_id: str,
    channel: str,
    registry: "UserRegistry",
    state: "ChannelState",
) -> str | None:
    """Parse and execute a bot command.

    Commands require ``!`` prefix: ``!register shepardxia``.

    Returns response string on command, ``None`` if not a command.
    """
    text = content.strip()

    # Normalize Chinese punctuation
    text = text.translate(_PUNCT_MAP)

    # ! prefix → command mode
    if not text.startswith("!"):
        return None

    cmd_text = text[1:].strip()
    if not cmd_text:
        return _help_message()

    try:
        cmd = parse(cmd_text)
    except ParseError:
        first_word = cmd_text.split()[0].lower() if cmd_text.split() else ""
        if first_word in COMMANDS:
            # Known command but garbled syntax — fall through to agent
            # so it can help the user format it correctly
            return None
        return _help_message()

    executor = CommandExecutor(registry, state)
    return executor.execute(cmd, sender_id, chat_id, channel)
