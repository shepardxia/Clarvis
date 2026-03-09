"""ChatBridge -- streaming Unix socket server for the chat TUI.

Bidirectional NDJSON protocol between the daemon and a single
``clarvis chat`` TUI client.  Pi RPC events are forwarded verbatim;
TUI commands are dispatched to the selected agent.

Supports multiple agents via an init handshake: the first message
from the client can be ``{"type": "init", "agent": "factoria"}``
to select a non-default agent.  Defaults to "clarvis".
"""

import asyncio
import json
import logging
from contextlib import aclosing
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..agent.agent import Agent
    from ..core.state import StateStore

logger = logging.getLogger(__name__)

CHAT_SOCKET_PATH = Path("/tmp/clarvis-chat.sock")


class ChatBridge:
    """Streaming Unix socket server for the chat TUI.

    Accepts a single persistent client.  Proxies Pi RPC events to
    the TUI and dispatches TUI commands to the active agent.
    """

    def __init__(
        self,
        agents: dict[str, "Agent"],
        state: "StateStore",
        loop: asyncio.AbstractEventLoop,
        user_name: str = "You",
    ):
        self._agents = agents
        self._active_agent: "Agent | None" = agents.get("clarvis")
        self._state = state
        self._loop = loop
        self._user_name = user_name
        self._server: asyncio.AbstractServer | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._client_task: asyncio.Task | None = None
        self._streaming_task: asyncio.Task | None = None
        self._prev_status: str | None = None

    def start(self) -> None:
        """Start the chat socket server."""
        self._loop.create_task(self._start_server())

    async def _start_server(self) -> None:
        """Create the Unix socket server."""
        # Remove stale socket
        CHAT_SOCKET_PATH.unlink(missing_ok=True)

        self._server = await asyncio.start_unix_server(
            self._handle_connection,
            path=str(CHAT_SOCKET_PATH),
        )
        logger.info("ChatBridge listening on %s", CHAT_SOCKET_PATH)

    async def _handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle a new TUI client connection (replaces previous)."""
        # Disconnect previous client
        if self._writer:
            await self._disconnect_client()

        self._reader = reader
        self._writer = writer
        # Reset to default agent for each new connection
        self._active_agent = self._agents.get("clarvis")
        logger.info("Chat TUI connected")

        self._client_task = asyncio.current_task()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                await self._dispatch(msg)
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Chat client error")
        finally:
            # Cancel any in-flight streaming and interrupt agent to release lock
            await self._disconnect_client()
            if self._active_agent and self._active_agent.is_busy:
                await self._active_agent.interrupt()
            self._reader = None
            self._client_task = None
            logger.info("Chat TUI disconnected")

    async def _dispatch(self, msg: dict) -> None:
        """Dispatch an inbound TUI message."""
        mtype = msg.get("type")

        if mtype == "init":
            self._handle_init(msg)

        elif mtype == "prompt":
            text = msg.get("message", "")
            if not text:
                return
            await self._handle_prompt(text)

        elif mtype == "abort":
            if self._active_agent:
                await self._active_agent.interrupt()

        elif mtype == "new_session":
            if self._active_agent:
                await self._active_agent.reset()
            self._send_to_client({"type": "session_reset"})

        elif mtype == "extension_ui_response":
            # Forward TUI's UI response to Pi stdin
            if self._active_agent:
                self._active_agent.forward_ui_response(msg)

        elif mtype == "command":
            cmd_name = msg.get("command", "")
            cmd_args = msg.get("args", {})
            if cmd_name:
                await self._handle_command(cmd_name, cmd_args, msg.get("id"))

        elif mtype == "get_state":
            self._handle_get_state()

        elif mtype == "get_messages":
            await self._handle_get_messages(msg.get("id"))

        elif mtype == "get_fork_messages":
            await self._handle_get_fork_messages(msg.get("id"))

        elif mtype == "fork":
            entry_id = msg.get("entryId", "")
            if entry_id:
                await self._handle_fork(entry_id, msg.get("id"))

    def _handle_init(self, msg: dict) -> None:
        """Handle init handshake -- select agent for this session."""
        name = msg.get("agent", "clarvis")
        req_id = msg.get("id")
        agent = self._agents.get(name)
        if agent:
            self._active_agent = agent
            resp: dict = {
                "type": "init_ack",
                "agent": name,
                "user_name": self._user_name,
                "session_key": agent.session_key,
            }
            if req_id:
                resp["id"] = req_id
            self._send_to_client(resp)
            logger.info("Chat TUI selected agent: %s", name)
        else:
            self._send_to_client(
                {
                    "type": "error",
                    "message": f"Unknown agent: {name}",
                }
            )

    async def _handle_command(self, command: str, args: dict, req_id: str | None = None) -> None:
        """Forward a Pi RPC command (e.g. /thinking, /model) to the agent."""
        agent = self._require_idle_agent()
        if not agent:
            return
        try:
            data = await agent.command(command, **args)
            # Persist settings changes to config.json
            self._persist_setting(command, args, data)
            resp: dict = {"type": "command_result", "command": command, "result": data}
            if req_id:
                resp["id"] = req_id
            self._send_to_client(resp)
        except Exception as exc:
            logger.warning("command %s failed: %s", command, exc)
            resp = {"type": "error", "message": f"{command}: {exc}"}
            if req_id:
                resp["id"] = req_id
            self._send_to_client(resp)

    def _persist_setting(self, command: str, args: dict, data: dict) -> None:
        """Save thinking/model changes to config.json for persistence."""
        from clarvis.core.persistence import json_load_safe, json_save_atomic
        from clarvis.display.config import CONFIG_PATH

        if command == "set_thinking_level":
            level = args.get("level")
            if level:
                raw = json_load_safe(CONFIG_PATH) or {}
                raw.setdefault("clarvis", {})["thinking"] = level
                json_save_atomic(CONFIG_PATH, raw)
                logger.info("Persisted thinking level: %s", level)
        elif command == "set_model":
            model_id = data.get("model", {}).get("modelId") if isinstance(data, dict) else None
            if model_id:
                raw = json_load_safe(CONFIG_PATH) or {}
                raw.setdefault("clarvis", {})["model"] = model_id
                json_save_atomic(CONFIG_PATH, raw)
                logger.info("Persisted model: %s", model_id)

    def _handle_get_state(self) -> None:
        """Send current state to client."""
        status = self._state.get("status") or {}
        response: dict[str, Any] = {
            "type": "state",
            "status": status.get("status", "idle"),
        }
        if self._active_agent:
            response["agent_busy"] = self._active_agent.is_busy
            response["agent_owner"] = self._active_agent.send_owner
            response["session_key"] = self._active_agent.session_key
        self._send_to_client(response)

    def _require_idle_agent(self) -> "Agent | None":
        """Return the active agent if present and idle, else send error and return None."""
        if not self._active_agent:
            return None
        if self._active_agent.is_busy:
            self._send_to_client({"type": "error", "message": "Agent busy"})
            return None
        return self._active_agent

    async def _handle_get_messages(self, req_id: str | None = None) -> None:
        """Fetch conversation history from the active agent."""
        agent = self._require_idle_agent()
        if not agent:
            return
        try:
            data = await agent.command("get_messages")
            resp: dict = {
                "type": "history",
                "messages": data.get("messages", []),
            }
            if req_id:
                resp["id"] = req_id
            self._send_to_client(resp)
        except Exception as exc:
            logger.warning("get_messages failed: %s", exc)
            self._send_to_client({"type": "error", "message": str(exc)})

    async def _handle_get_fork_messages(self, req_id: str | None = None) -> None:
        """Fetch fork-eligible messages from the active agent."""
        agent = self._require_idle_agent()
        if not agent:
            return
        try:
            data = await agent.command("get_fork_messages")
            resp: dict = {
                "type": "fork_messages",
                "messages": data.get("messages", []),
            }
            if req_id:
                resp["id"] = req_id
            self._send_to_client(resp)
        except Exception as exc:
            logger.warning("get_fork_messages failed: %s", exc)
            self._send_to_client({"type": "error", "message": str(exc)})

    async def _handle_fork(self, entry_id: str, req_id: str | None = None) -> None:
        """Fork the conversation at the given entry."""
        agent = self._require_idle_agent()
        if not agent:
            return
        try:
            data = await agent.command("fork", entryId=entry_id)
            resp: dict = {
                "type": "fork_complete",
                "text": data.get("text", ""),
                "cancelled": data.get("cancelled", False),
            }
            if req_id:
                resp["id"] = req_id
            self._send_to_client(resp)
            # If fork succeeded (not cancelled), send updated history
            if not data.get("cancelled", False):
                history = await agent.command("get_messages")
                self._send_to_client(
                    {
                        "type": "history",
                        "messages": history.get("messages", []),
                    }
                )
        except Exception as exc:
            logger.warning("fork failed: %s", exc)
            self._send_to_client({"type": "error", "message": str(exc)})

    async def _handle_prompt(self, text: str) -> None:
        """Send a prompt to the agent, streaming events to the TUI."""
        if not self._active_agent:
            self._send_to_client({"type": "error", "message": "No agent selected"})
            return

        # Check if agent is busy
        if self._active_agent.is_busy:
            owner = self._active_agent.send_owner or "unknown"
            self._send_to_client(
                {
                    "type": "error",
                    "message": f"Agent busy ({owner} pipeline active)",
                }
            )
            return

        # Cancel any previous streaming task
        if self._streaming_task and not self._streaming_task.done():
            self._streaming_task.cancel()

        self._streaming_task = asyncio.create_task(self._stream_prompt(text))

    async def _stream_prompt(self, text: str) -> None:
        """Stream a prompt through the agent to the TUI."""
        agent = self._active_agent
        if not agent:
            return

        # No context injection for chat — user sees exactly what's sent
        enriched = text

        # Push thinking status
        self._save_and_push_status("thinking")

        try:
            async with aclosing(agent.send(enriched, owner="chat")) as stream:
                async for event in stream:
                    self._send_to_client(event)

                    etype = event.get("type")
                    if etype == "agent_end":
                        break
                    elif etype == "message_update":
                        self._push_status("responding")
        except Exception as exc:
            logger.warning("Chat stream error: %s", exc)
            self._send_to_client({"type": "error", "message": str(exc)})
        finally:
            self._restore_status()

    def _send_to_client(self, data: dict) -> None:
        """Send an NDJSON line to the connected TUI client."""
        if not self._writer:
            return
        try:
            line = json.dumps(data, ensure_ascii=False) + "\n"
            self._writer.write(line.encode())
        except Exception:
            logger.debug("Failed to write to chat client")

    def _save_and_push_status(self, status: str) -> None:
        """Save current status and push a new one for the chat session."""
        current = self._state.get("status") or {}
        self._prev_status = current.get("status", "idle")
        current["status"] = status
        self._state.update("status", current)

    def _push_status(self, status: str) -> None:
        """Update display status without saving the previous."""
        current = self._state.get("status") or {}
        if current.get("status") != status:
            current["status"] = status
            self._state.update("status", current)

    def _restore_status(self) -> None:
        """Restore the status saved before the chat session started."""
        if self._prev_status is not None:
            current = self._state.get("status") or {}
            current["status"] = self._prev_status
            self._state.update("status", current)
            self._prev_status = None

    async def _disconnect_client(self) -> None:
        """Disconnect the current client."""
        if self._streaming_task and not self._streaming_task.done():
            self._streaming_task.cancel()
            try:
                await self._streaming_task
            except asyncio.CancelledError:
                pass
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None

    def stop(self) -> None:
        """Stop the chat bridge server."""
        if self._server:
            self._server.close()
            CHAT_SOCKET_PATH.unlink(missing_ok=True)
            logger.info("ChatBridge stopped")
