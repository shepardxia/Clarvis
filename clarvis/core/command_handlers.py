"""IPC command handlers for daemon IPC commands and state queries.

Each handler is a thin wrapper that queries StateStore or delegates to
the appropriate service (refresh, session_tracker, etc.).
"""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from .context import AppContext

from ..display.refresh_manager import RefreshManager
from ..formatters.memory import (
    fmt_bank_profile,
    fmt_bank_stats,
    fmt_directives,
    fmt_facts,
    fmt_mental_models,
    fmt_observations,
    fmt_stale_models,
)
from ..services.session_tracker import SessionTracker
from .ipc import DaemonServer

_STAGING_DIR = Path.home() / ".clarvis" / "staging"


class CommandHandlers:
    """Registers and implements IPC command handlers for the daemon.

    All state access goes through the injected StateStore. Service
    delegation goes through the injected manager instances.
    """

    def __init__(
        self,
        ctx: "AppContext",
        session_tracker: SessionTracker,
        refresh: RefreshManager,
        command_server: DaemonServer,
        services: dict[str, Callable[[], Any | None]] | None = None,
    ):
        self.ctx = ctx
        self.session_tracker = session_tracker
        self.refresh = refresh
        self.command_server = command_server
        self._services = services or {}

    def register_all(self) -> None:
        """Register all command handlers with the IPC server."""
        reg = self.command_server.register

        # State queries
        reg("get_state", self.get_state)
        reg("get_status", self.get_status)
        reg("get_weather", self.get_weather)
        reg("get_sessions", self.get_sessions)
        reg("get_session", self.get_session)

        # Actions
        reg("refresh_weather", self.refresh.refresh_weather)
        reg("refresh_time", self.refresh.refresh_time)
        reg("refresh_location", self.refresh_location)
        reg("refresh_all", self.refresh_all)

        # Voice context
        reg("get_voice_context", self.get_voice_context)

        # Voice session management
        reg("reset_clarvis_session", self.reset_clarvis_session)

        # Memory
        reg("memory_ingest", self.memory_ingest)
        reg("checkin", self.checkin)

        # Agent management
        reg("reload_agents", self.reload_agents)

        # Agent tools (ctools) — memory
        reg("recall", self.recall_memory)
        reg("remember", self.remember_fact)
        reg("update_fact", self.update_fact)
        reg("forget", self.forget)
        reg("list_facts", self.list_facts)
        reg("stats", self.stats)
        reg("audit", self.audit)

        # Agent tools (ctools) — mental models
        reg("list_models", self.list_models)
        reg("search_models", self.search_models)
        reg("create_model", self.create_model)
        reg("update_model", self.update_model)
        reg("delete_model", self.delete_model)

        # Agent tools (ctools) — observations & consolidation
        reg("list_observations", self.list_observations)
        reg("get_observation", self.get_observation)
        reg("unconsolidated", self.unconsolidated)
        reg("related_observations", self.related_observations)
        reg("consolidate", self.consolidate)
        reg("stale_models", self.stale_models)

        # Agent tools (ctools) — directives
        reg("list_directives", self.list_directives)
        reg("create_directive", self.create_directive)
        reg("update_directive", self.update_directive)
        reg("delete_directive", self.delete_directive)

        # Agent tools (ctools) — bank profile
        reg("get_profile", self.get_profile)
        reg("set_mission", self.set_mission)
        reg("set_disposition", self.set_disposition)

        # Agent tools (ctools) — knowledge graph
        reg("knowledge", self.knowledge)
        reg("ingest", self.ingest)
        reg("entities", self.entities)
        reg("relations", self.relations)
        reg("update_entity", self.update_entity)
        reg("merge_entities", self.merge_entities)
        reg("delete_entity", self.delete_entity)
        reg("build_communities", self.build_communities)

        # Agent tools (ctools) — channels
        reg("send_message", self.send_message)
        reg("get_channels", self.get_channels)

        # Agent tools (ctools) — core
        reg("stage_memory", self.stage_memory)
        reg("prompt_response", self.prompt_response)
        reg("reflect_complete", self.reflect_complete)
        reg("read_pending_sessions", self.read_pending_sessions)
        reg("read_remember_queue", self.read_remember_queue)

        # Agent tools (ctools) — spotify & timers
        reg("spotify", self.spotify)
        reg("timer", self.timer)

        # Utility
        reg("ping", lambda: "pong")

    def _get_service(self, name: str):
        """Get a service by name from the services dict."""
        provider = self._services.get(name)
        return provider() if provider else None

    # --- State queries ---

    def get_state(self) -> dict:
        """Get full Clarvis state."""
        status = self.ctx.state.get("status")
        weather = self.ctx.state.get("weather")
        time_data = self.ctx.state.get("time")
        sessions = self.ctx.state.get("sessions")

        session_details = {}
        for session_id, data in sessions.items():
            session_details[session_id] = {
                "last_status": data.get("last_status", "unknown"),
                "last_context": data.get("last_context", 0),
                "status_history": data.get("status_history", []),
                "context_history": data.get("context_history", []),
            }

        return {
            "displayed_session": status.get("session_id"),
            "status": status.get("status", "unknown"),
            "context_percent": status.get("context_percent", 0),
            "status_history": status.get("status_history", []),
            "context_history": status.get("context_history", []),
            "weather": {
                "type": weather.get("description", "unknown"),
                "temperature": weather.get("temperature"),
                "wind_speed": weather.get("wind_speed", 0),
                "intensity": weather.get("intensity", 0),
                "city": weather.get("city", "unknown"),
                "widget_type": weather.get("widget_type", "clear"),
            },
            "time": time_data.get("timestamp"),
            "sessions": session_details,
        }

    def get_status(self) -> dict:
        """Get current status."""
        return self.ctx.state.get("status")

    def get_weather(self) -> dict:
        """Get current weather."""
        return self.ctx.state.get("weather")

    def get_sessions(self) -> list:
        """List all tracked sessions."""
        return self.session_tracker.list_all()

    def get_session(self, session_id: str) -> dict:
        """Get details for a specific session."""
        return self.session_tracker.get_details(session_id)

    # --- Actions ---

    def refresh_location(self) -> dict:
        """Refresh location and return new data."""
        lat, lon, city = self.refresh.refresh_location()
        return {"latitude": lat, "longitude": lon, "city": city}

    def refresh_all(self) -> str:
        """Refresh all data sources."""
        self.refresh.refresh_all()
        return "ok"

    # --- Voice context ---

    def get_voice_context(self) -> dict:
        """Return the context snapshot that would be prepended to a voice command."""
        status = self.ctx.state.get("status")
        weather = self.ctx.state.get("weather")
        time_data = self.ctx.state.get("time")

        ctx: dict = {
            "status": status.get("status", "idle"),
            "context_percent": status.get("context_percent", 0),
            "tool_history": status.get("tool_history", [])[-5:],
        }

        if weather.get("temperature"):
            ctx["weather"] = {
                "temperature": weather.get("temperature"),
                "description": weather.get("description", ""),
            }

        if time_data.get("timestamp"):
            ctx["time"] = time_data["timestamp"]

        orchestrator = self._get_service("voice")
        ctx["formatted"] = orchestrator.build_voice_context() if orchestrator else ""

        return ctx

    # --- Voice session management ---

    def reset_clarvis_session(self) -> str:
        """Disconnect Clarvis agent so next interaction starts a fresh session."""
        import asyncio

        # Remove agent session ID files so next interaction starts fresh
        for sid_file in [
            Path.home() / ".clarvis" / "clarvis" / "session_id",
            Path.home() / ".clarvis" / "factoria" / "session_id",
        ]:
            sid_file.unlink(missing_ok=True)

        # Disconnect Clarvis agent (it'll reconnect fresh on next interaction)
        orchestrator = self._get_service("voice")
        if orchestrator and orchestrator.agent.connected:
            asyncio.run_coroutine_threadsafe(orchestrator.agent.disconnect(), orchestrator._loop)

        return "ok"

    def reload_agents(self, **kwargs) -> dict:
        """Reload agent prompts and context files (CLAUDE.md / AGENTS.md).

        For Pi backends, triggers session.reload() which re-reads context files,
        skills, and extensions. For Claude Code backends, this is a no-op since
        CLAUDE.md is re-read per turn.
        """
        import asyncio

        agents = self._get_service("agents") or {}
        if not agents:
            return {"error": "No agents initialized"}

        reloaded = []
        errors = []

        for name, agent in agents.items():
            backend = getattr(agent, "_backend", None)
            reload_fn = getattr(backend, "reload", None)
            if reload_fn is None:
                reloaded.append(f"{name}: skipped (no reload support)")
                continue
            try:
                loop = getattr(agent, "_loop", None)
                if loop is None:
                    errors.append(f"{name}: no event loop")
                    continue
                asyncio.run_coroutine_threadsafe(reload_fn(), loop).result(timeout=15)
                reloaded.append(f"{name}: ok")
            except Exception as exc:
                errors.append(f"{name}: {exc}")

        return {"status": "ok", "reloaded": reloaded, "errors": errors}

    def memory_ingest(self, **kwargs) -> dict:
        """Trigger memory maintenance (called by `clarvis rem`).

        Sends a forced reflect nudge to the persistent Clarvis agent
        via WakeupManager. The agent runs /reflect to extract facts
        from pending sessions and consolidate.
        """
        import asyncio

        wakeup = self._get_service("wakeup")
        if not wakeup:
            return {"error": "WakeupManager not available"}

        try:
            result = asyncio.run_coroutine_threadsafe(
                wakeup.on_force_reflect(),
                self.ctx.loop,
            ).result(timeout=120)
            return {"status": "ok", "response": result}
        except Exception as exc:
            return {"error": str(exc)}

    def checkin(self, **kwargs) -> dict:
        """Prepare for interactive checkin session (called by `clarvis checkin`).

        Scaffolds checkin files (skill prompt + seed goals YAML) if missing,
        seeds goals into Hindsight if needed (first-run), then returns status
        so the CLI can launch an interactive Claude session with the checkin skill.
        """
        import asyncio

        from clarvis.agent.memory.goals import GoalSeeder, scaffold_checkin_files

        store = self._get_service("hindsight_store")

        result: dict = {"status": "ok", "goals_seeded": 0}

        # Scaffold checkin files (seed_goals.yaml, skills/checkin.md)
        home_dir = Path.home() / ".clarvis" / "clarvis"
        scaffolded = scaffold_checkin_files(home_dir)
        result["scaffolded"] = scaffolded

        # Seed goals if needed
        if store and store.ready:
            try:
                seed_path = home_dir / "seed_goals.yaml"
                seeder = GoalSeeder(seed_path=seed_path, backend=store)
                seeded = asyncio.run_coroutine_threadsafe(
                    seeder.seed_if_needed(),
                    self.ctx.loop,
                ).result(timeout=30)
                result["goals_seeded"] = len(seeded)
            except Exception as exc:
                result["goals_error"] = str(exc)
        else:
            result["memory_warning"] = "Memory service not available"

        return result

    # --- Agent tools (ctools) --- helpers ---

    def _memory_op(self, fn, timeout=30):
        """Run an async HindsightStore operation. Returns result or error dict."""
        import asyncio

        store = self._get_service("hindsight_store")
        if store is None or not store.ready:
            return {"error": "Memory not available"}
        try:
            return asyncio.run_coroutine_threadsafe(fn(store), self.ctx.loop).result(timeout=timeout)
        except Exception as exc:
            return {"error": str(exc)}

    def _cognee_op(self, fn, timeout=30):
        """Run an async CogneeBackend operation. Returns result or error dict."""
        import asyncio

        backend = self._get_service("cognee_backend")
        if backend is None or not backend.ready:
            return {"error": "Knowledge service not available"}
        try:
            return asyncio.run_coroutine_threadsafe(fn(backend), self.ctx.loop).result(timeout=timeout)
        except Exception as exc:
            return {"error": str(exc)}

    # --- Memory: facts ---

    def recall_memory(
        self, *, query: str, bank: str = "parletre", fact_type: str | None = None, tags: list[str] | None = None, **kw
    ) -> str | dict:
        fact_types = [fact_type] if fact_type else None
        result = self._memory_op(lambda s: s.recall(query, bank=bank, fact_type=fact_types, tags=tags))
        if isinstance(result, dict) and "error" in result:
            return result
        results = result.get("results") or result.get("facts") or []
        if not results:
            return "No memories found."
        return f"Results:\n{fmt_facts(results)}"

    def remember_fact(
        self,
        *,
        text: str,
        fact_type: str = "world",
        bank: str = "parletre",
        entities: list[str] | None = None,
        confidence: float | None = None,
        tags: list[str] | None = None,
        **kw,
    ) -> str | dict:
        from clarvis.vendor.hindsight.engine.retain.types import FactInput

        fact = FactInput(
            fact_text=text, fact_type=fact_type, entities=entities or [], confidence=confidence, tags=tags or []
        )

        def _do(s):
            async def _run():
                ids = await s.store_facts([fact], bank=bank)
                return {"stored": len(ids), "fact_ids": ids}

            return _run()

        result = self._memory_op(_do)
        if isinstance(result, dict) and "error" in result:
            return result
        fact_ids = result.get("fact_ids", [])
        if not fact_ids:
            return "Stored (no fact IDs returned)."
        lines = [f"  [{fact_type}] id:{str(fid)[:12]}" for fid in fact_ids]
        return "Stored:\n" + "\n".join(lines)

    def update_fact(
        self,
        *,
        fact_id: str,
        content: str | None = None,
        fact_type: str | None = None,
        confidence: float | None = None,
        bank: str = "parletre",
        **kw,
    ) -> str | dict:
        if content is None:
            return {"error": "content is required for update"}
        result = self._memory_op(
            lambda s: s.update_fact(fact_id, bank=bank, content=content, fact_type=fact_type, confidence=confidence)
        )
        if isinstance(result, dict) and "error" in result:
            return result
        if result.get("success"):
            new_ids = result.get("new_ids", [])
            return f"Updated. Old: {fact_id[:12]}, New: {', '.join(str(i)[:12] for i in new_ids)}"
        return f"Update failed: {result.get('message', 'unknown error')}"

    def forget(self, *, fact_id: str, **kw) -> str | dict:
        result = self._memory_op(lambda s: s.delete_fact(fact_id))
        if isinstance(result, dict) and "error" in result:
            return result
        return f"Forgotten: {fact_id[:12]}"

    def list_facts(self, *, bank: str = "parletre", fact_type: str | None = None, limit: int = 50, **kw) -> str | dict:
        result = self._memory_op(lambda s: s.list_facts(bank, fact_type=fact_type, limit=limit))
        if isinstance(result, dict) and "error" in result:
            return result
        items = result.get("items", []) if isinstance(result, dict) else result
        if not items:
            return "No memories found."
        total = result.get("total", len(items)) if isinstance(result, dict) else len(items)
        header = f"Showing {len(items)} of {total} facts"
        if fact_type:
            header += f" (type: {fact_type})"
        return f"{header}:\n{fmt_facts(items)}"

    # --- Memory: stats & audit ---

    def stats(self, *, bank: str = "parletre", **kw) -> str | dict:
        result = self._memory_op(lambda s: s.get_bank_stats(bank))
        if isinstance(result, dict) and "error" in result:
            return result
        return fmt_bank_stats(bank, result)

    def audit(self, *, bank: str = "parletre", **kw) -> str | dict:
        from datetime import datetime, timedelta, timezone

        from ..core.time_utils import is_after

        async def _do(s):
            since = datetime.now(timezone.utc) - timedelta(days=1)
            cap = 30
            facts_result = await s.list_facts(bank, limit=cap * 3)
            facts = facts_result.get("items", []) if isinstance(facts_result, dict) else facts_result
            recent_facts = [f for f in facts if is_after(f, since)][:cap]
            observations = await s.list_observations(bank, limit=cap * 3)
            recent_obs = [o for o in observations if is_after(o, since)][:cap]
            models = await s.list_mental_models(bank)
            recent_models = [m for m in models if is_after(m, since)][:cap]
            return {
                "since": since.isoformat(),
                "recent_facts": recent_facts,
                "recent_observations": recent_obs,
                "recent_models": recent_models,
            }

        result = self._memory_op(_do, timeout=60)
        if isinstance(result, dict) and "error" in result:
            return result

        since = result["since"]
        parts = []
        recent_facts = result["recent_facts"]
        parts.append(f"Facts since {since} ({len(recent_facts)}):")
        parts.append(fmt_facts(recent_facts) if recent_facts else "  (none)")
        recent_obs = result["recent_observations"]
        parts.append(f"\nObservations since {since} ({len(recent_obs)}):")
        parts.append(fmt_observations(recent_obs) if recent_obs else "  (none)")
        recent_models = result["recent_models"]
        parts.append(f"\nMental models since {since} ({len(recent_models)}):")
        parts.append(fmt_mental_models(recent_models) if recent_models else "  (none)")
        return "\n".join(parts)

    # --- Memory: mental models ---

    def list_models(self, *, bank: str = "parletre", **kw) -> str | dict:
        result = self._memory_op(lambda s: s.list_mental_models(bank))
        if isinstance(result, dict) and "error" in result:
            return result
        if not result:
            return "No mental models."
        return f"Mental models ({len(result)}):\n{fmt_mental_models(result)}"

    def search_models(self, *, query: str, bank: str = "parletre", tags: list[str] | None = None, **kw) -> str | dict:
        result = self._memory_op(lambda s: s.search_mental_models(query, bank=bank, tags=tags))
        if isinstance(result, dict) and "error" in result:
            return result
        models = result.get("results", []) if isinstance(result, dict) else result
        if not models:
            return "No matching mental models."
        return f"Matching models ({len(models)}):\n{fmt_mental_models(models)}"

    def create_model(
        self, *, name: str, content: str, source_query: str, bank: str = "parletre", tags: list[str] | None = None, **kw
    ) -> str | dict:
        result = self._memory_op(lambda s: s.create_mental_model(bank, name, content, source_query, tags=tags))
        if isinstance(result, dict) and "error" in result:
            return result
        mid = str(result.get("id", "?"))[:12]
        return f"Created mental model '{name}' [id:{mid}]"

    def update_model(
        self, *, id: str, bank: str = "parletre", content: str | None = None, name: str | None = None, **kw
    ) -> str | dict:
        result = self._memory_op(lambda s: s.update_mental_model(bank, id, content=content, name=name))
        if isinstance(result, dict) and "error" in result:
            return result
        return f"Updated mental model [id:{id[:12]}]"

    def delete_model(self, *, id: str, bank: str = "parletre", **kw) -> str | dict:
        result = self._memory_op(lambda s: s.delete_mental_model(bank, id))
        if isinstance(result, dict) and "error" in result:
            return result
        return f"Deleted mental model [id:{id[:12]}]"

    # --- Memory: observations & consolidation ---

    def list_observations(self, *, bank: str = "parletre", limit: int = 50, **kw) -> str | dict:
        result = self._memory_op(lambda s: s.list_observations(bank, limit=limit))
        if isinstance(result, dict) and "error" in result:
            return result
        if not result:
            return "No observations."
        return f"Observations ({len(result)}):\n{fmt_observations(result)}"

    def get_observation(self, *, id: str, bank: str = "parletre", include_sources: bool = True, **kw) -> str | dict:
        result = self._memory_op(lambda s: s.get_observation(bank, id, include_source_facts=include_sources))
        if isinstance(result, dict) and "error" in result:
            return result
        if result is None:
            return f"Observation {id[:12]} not found."
        content = result.get("content") or result.get("summary") or ""
        tags = result.get("tags", [])
        parts = [f"Observation [id:{id[:12]}]:", content]
        if tags:
            parts.append(f"Tags: {', '.join(tags)}")
        source_facts = result.get("source_facts") or result.get("source_memories") or []
        if source_facts:
            parts.append(f"\nSource facts ({len(source_facts)}):")
            parts.append(fmt_facts(source_facts))
        return "\n".join(parts)

    def unconsolidated(self, *, bank: str = "parletre", limit: int = 100, **kw) -> str | dict:
        result = self._memory_op(lambda s: s.get_unconsolidated(bank, limit=limit))
        if isinstance(result, dict) and "error" in result:
            return result
        facts = result.get("facts", []) if isinstance(result, dict) else []
        if not facts:
            return f"No unconsolidated facts in bank '{bank}'."
        return f"{len(facts)} unconsolidated facts:\n{fmt_facts(facts)}"

    def related_observations(self, *, fact_ids: list[str], bank: str = "parletre", **kw) -> str | dict:
        async def _do(s):
            fact_texts, fact_tags = [], []
            for fid in fact_ids:
                fact = await s.get_fact(bank, fid)
                if fact:
                    fact_texts.append(fact.get("content") or fact.get("text") or fact.get("fact_text") or "")
                    fact_tags.append(fact.get("tags") or [])
                else:
                    fact_texts.append("")
                    fact_tags.append([])
            return await s.get_related_observations(bank, fact_texts, fact_tags)

        result = self._memory_op(_do)
        if isinstance(result, dict) and "error" in result:
            return result
        observations = result.get("observations", []) if isinstance(result, dict) else []
        if not observations:
            return "No related observations found."
        return f"{len(observations)} related observations:\n{fmt_observations(observations)}"

    def consolidate(
        self, *, decisions: list[dict], fact_ids_to_mark: list[str], bank: str = "parletre", **kw
    ) -> str | dict:
        from clarvis.vendor.hindsight.engine.retain.types import ConsolidationDecision

        try:
            parsed = [
                ConsolidationDecision(
                    action=d["action"],
                    text=d.get("text", ""),
                    source_fact_ids=d.get("source_fact_ids", []),
                    observation_id=d.get("observation_id"),
                )
                for d in decisions
            ]
        except (KeyError, TypeError) as exc:
            return {"error": f"Invalid decisions: {exc}"}
        result = self._memory_op(lambda s: s.apply_consolidation_decisions(bank, parsed, fact_ids_to_mark))
        if isinstance(result, dict) and "error" in result:
            return result
        created = result.get("created", 0) if isinstance(result, dict) else 0
        updated = result.get("updated", 0) if isinstance(result, dict) else 0
        deleted = result.get("deleted", 0) if isinstance(result, dict) else 0
        marked = result.get("marked", 0) if isinstance(result, dict) else len(fact_ids_to_mark)
        return (
            f"Consolidation applied: {created} created, {updated} updated, "
            f"{deleted} deleted, {marked} facts marked as consolidated."
        )

    def stale_models(self, *, bank: str = "parletre", **kw) -> str | dict:
        result = self._memory_op(lambda s: s.list_models_needing_refresh(bank))
        if isinstance(result, dict) and "error" in result:
            return result
        return fmt_stale_models(result)

    # --- Memory: directives ---

    def list_directives(
        self, *, bank: str = "parletre", active_only: bool = True, tags: list[str] | None = None, **kw
    ) -> str | dict:
        result = self._memory_op(lambda s: s.list_directives(bank, tags=tags, active_only=active_only))
        if isinstance(result, dict) and "error" in result:
            return result
        return fmt_directives(result)

    def create_directive(
        self, *, name: str, content: str, bank: str = "parletre", priority: int = 0, tags: list[str] | None = None, **kw
    ) -> str | dict:
        result = self._memory_op(lambda s: s.create_directive(bank, name, content, priority=priority, tags=tags))
        if isinstance(result, dict) and "error" in result:
            return result
        did = str(result.get("id", "?"))[:12]
        return f"Created directive '{name}' [id:{did}]"

    def update_directive(
        self,
        *,
        directive_id: str,
        bank: str = "parletre",
        content: str | None = None,
        priority: int | None = None,
        is_active: bool | None = None,
        tags: list[str] | None = None,
        **kw,
    ) -> str | dict:
        result = self._memory_op(
            lambda s: s.update_directive(
                bank, directive_id, content=content, priority=priority, is_active=is_active, tags=tags
            )
        )
        if isinstance(result, dict) and "error" in result:
            return result
        return f"Updated directive [id:{directive_id[:12]}]"

    def delete_directive(self, *, directive_id: str, bank: str = "parletre", **kw) -> str | dict:
        result = self._memory_op(lambda s: s.delete_directive(bank, directive_id))
        if isinstance(result, dict) and "error" in result:
            return result
        return f"Deleted directive [id:{directive_id[:12]}]"

    # --- Memory: bank profile ---

    def get_profile(self, *, bank: str = "parletre", **kw) -> str | dict:
        result = self._memory_op(lambda s: s.get_bank_profile(bank))
        if isinstance(result, dict) and "error" in result:
            return result
        return fmt_bank_profile(bank, result)

    def set_mission(self, *, mission: str, bank: str = "parletre", **kw) -> str | dict:
        result = self._memory_op(lambda s: s.set_bank_mission(bank, mission))
        if isinstance(result, dict) and "error" in result:
            return result
        return f"Updated mission for bank '{bank}'."

    def set_disposition(
        self,
        *,
        bank: str = "parletre",
        skepticism: int | None = None,
        literalism: int | None = None,
        empathy: int | None = None,
        **kw,
    ) -> str | dict:
        result = self._memory_op(
            lambda s: s.update_bank_disposition(bank, skepticism=skepticism, literalism=literalism, empathy=empathy)
        )
        if isinstance(result, dict) and "error" in result:
            return result
        changed = []
        if skepticism is not None:
            changed.append(f"skepticism={skepticism}")
        if literalism is not None:
            changed.append(f"literalism={literalism}")
        if empathy is not None:
            changed.append(f"empathy={empathy}")
        return f"Updated disposition for bank '{bank}': {', '.join(changed)}"

    # --- Knowledge graph (Cognee) ---

    def knowledge(
        self, *, query: str, search_type: str = "graph_completion", datasets: str | None = None, **kw
    ) -> str | dict:
        ds_list = [s.strip() for s in datasets.split(",")] if datasets else None
        return self._cognee_op(lambda b: b.search(query, search_type=search_type, datasets=ds_list, format=True))

    def ingest(self, *, content_or_path: str, dataset: str = "knowledge", tags: str | None = None, **kw) -> str | dict:
        tag_list = [t.strip() for t in tags.split(",")] if tags else None
        return self._cognee_op(lambda b: b.ingest(content_or_path, dataset=dataset, tags=tag_list, format=True))

    def entities(self, *, type_name: str | None = None, name: str | None = None, **kw) -> str | dict:
        return self._cognee_op(lambda b: b.list_entities(type_name=type_name, name=name, format=True))

    def relations(self, *, entity_id: str | None = None, relationship_type: str | None = None, **kw) -> str | dict:
        return self._cognee_op(
            lambda b: b.list_facts(entity_id=entity_id, relationship_type=relationship_type, format=True)
        )

    def update_entity(self, *, entity_id: str, fields: dict, **kw) -> str | dict:
        return self._cognee_op(lambda b: b.update_entity(entity_id, fields, format=True))

    def merge_entities(self, *, entity_ids: list[str], **kw) -> str | dict:
        return self._cognee_op(lambda b: b.merge_entities(entity_ids, format=True))

    def delete_entity(self, *, node_id: str, **kw) -> str | dict:
        return self._cognee_op(lambda b: b.delete(node_id, format=True))

    def build_communities(self, **kw) -> str | dict:
        return self._cognee_op(lambda b: b.build_communities(format=True))

    # --- Channels ---

    def send_message(self, *, channel: str, chat_id: str, content: str, **kw) -> dict:
        import asyncio

        mgr = self._get_service("channel_manager")
        if mgr is None:
            return {"error": "Channel manager not available"}
        ch = mgr.get_channel(channel)
        if ch is None:
            return {"error": f"Channel '{channel}' not found. Available: {mgr.enabled_channels}"}
        try:
            ok = asyncio.run_coroutine_threadsafe(mgr.send_message(channel, chat_id, content), self.ctx.loop).result(
                timeout=30
            )
            return {"sent": ok}
        except Exception as exc:
            return {"error": str(exc)}

    def get_channels(self, **kw) -> dict:
        mgr = self._get_service("channel_manager")
        if mgr is None:
            return {"error": "Channel manager not available"}
        return mgr.get_status()

    # --- Core tools ---

    def stage_memory(self, *, summary: str, **kw) -> dict:
        from datetime import datetime, timezone

        from ..core.persistence import json_load_safe, json_save_atomic

        queue_file = _STAGING_DIR / "remember_queue.json"
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        items = json_load_safe(queue_file) or []
        items.append({"summary": summary, "timestamp": datetime.now(timezone.utc).isoformat()})
        json_save_atomic(queue_file, items)
        return {"queued": len(items)}

    def prompt_response(self, **kw) -> dict:
        if self.ctx.bus is None:
            return {"error": "Voice pipeline not available"}
        self.ctx.bus.emit("voice:prompt_reply")
        return {"status": "listening"}

    def read_pending_sessions(self, **kw) -> dict:
        reader = self._get_service("session_reader")
        if not reader:
            return {"error": "SessionReader not available"}
        pending = reader.read_pending()
        # Flatten to {source: [{role, text}, ...]} with counts
        summary = {}
        for source, messages in pending.items():
            summary[source] = {
                "count": len(messages),
                "messages": messages,
            }
        return summary

    def read_remember_queue(self, **kw) -> dict:
        from ..core.persistence import json_load_safe

        queue_file = _STAGING_DIR / "remember_queue.json"
        items = json_load_safe(queue_file) or []
        return {"count": len(items), "items": items}

    def reflect_complete(self, **kw) -> dict:
        import asyncio

        daemon = self._get_service("daemon")
        if not daemon:
            return {"error": "daemon not available"}
        try:
            result = asyncio.run_coroutine_threadsafe(daemon.complete_reflect(), self.ctx.loop).result(timeout=30)
            return result
        except Exception as exc:
            return {"error": str(exc)}

    # --- Spotify ---

    def spotify(self, *, command: str, **kw) -> str | dict:
        session = self._get_service("spotify_session")
        if session is None:
            return {"error": "Spotify not available"}
        try:
            return session.run(command)
        except Exception as e:
            return {"error": str(e)}

    # --- Timers ---

    def timer(
        self,
        *,
        action: str,
        name: str | None = None,
        duration: str | None = None,
        label: str | None = None,
        recurring: bool = False,
        wake_clarvis: bool = False,
        **kw,
    ) -> str | dict:
        svc = self._get_service("timer_service")
        if svc is None:
            return {"error": "Timer service not available"}

        if action == "set":
            if not name or not duration:
                return {"error": "set requires name and duration"}
            from clarvis.services.timer_service import parse_duration

            try:
                seconds = parse_duration(duration)
            except ValueError as e:
                return {"error": str(e)}
            timer = svc.set_timer(name, seconds, recurring, label or "", wake_clarvis)
            return f"Timer '{timer.name}' set for {timer.duration}s (fires at {timer.fire_at})"
        elif action == "list":
            timers = svc.list_timers()
            if not timers:
                return "No active timers."
            lines = []
            for t in timers:
                t_name = t.get("name", t) if isinstance(t, dict) else str(t)
                lines.append(f"  - {t_name}")
            return "Active timers:\n" + "\n".join(lines)
        elif action == "cancel":
            if not name:
                return {"error": "cancel requires name"}
            ok = svc.cancel(name)
            return f"Cancelled timer '{name}'" if ok else f"Timer '{name}' not found"
        else:
            return {"error": f"Unknown action: {action}"}
