"""Memory MCP sub-server — Hindsight conversational memory.

Exposes memory tools (search, add, update, forget, list, staged) that delegate
to the daemon's HindsightBackend and StagingStore.

All tools return natural language strings for agent readability.
Bank descriptions in tool schemas are auto-generated from config.

IMPORTANT: Do NOT use ``from __future__ import annotations`` in this file.
It breaks Pydantic's runtime ``Annotated`` resolution for JSON schema generation.
"""

import logging
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from ._helpers import get_daemon, make_lifespan

logger = logging.getLogger(__name__)


def _visibility(ctx: Context) -> str:
    return ctx.fastmcp._lifespan_result["visibility"]


def _fmt_facts(facts: list[dict]) -> str:
    """Format a list of fact dicts into numbered lines."""
    if not facts:
        return "No results."
    lines = []
    for i, fact in enumerate(facts, 1):
        fid = str(fact.get("id", "?"))[:12]
        ftype = fact.get("fact_type") or fact.get("type") or ""
        content = fact.get("content") or fact.get("text") or str(fact)
        confidence = fact.get("confidence")
        parts = [f"[{ftype}]" if ftype else "", content]
        if confidence is not None:
            parts.append(f"(confidence: {confidence})")
        line = " ".join(p for p in parts if p)
        lines.append(f"  {i}. [id:{fid}] {line}")
    return "\n".join(lines)


def create_memory_server(daemon, visibility: str = "master") -> FastMCP:
    """Create the memory MCP sub-server (Hindsight).

    Args:
        daemon: CentralHubDaemon instance.
        visibility: Access level for bank filtering.
            ``"master"`` sees all banks (parletre + agora).
            ``"all"`` sees only shared banks (agora).
    """
    server = FastMCP("Memory", lifespan=make_lifespan(daemon, visibility=visibility))

    # -- memory_search (available to all visibility levels) ----------------

    @server.tool()
    async def memory_search(
        query: Annotated[
            str,
            Field(description="Natural language query to search conversational memory."),
        ],
        bank: Annotated[
            str,
            Field(
                description=(
                    "Memory bank to search. 'parletre' = personal memory (Clarvis only). "
                    "'agora' = shared knowledge (all agents). "
                    "Masked agents can only search 'agora'."
                ),
            ),
        ] = "parletre",
        max_tokens: Annotated[
            int,
            Field(description="Token budget for results (default 4096)."),
        ] = 4096,
        fact_type: Annotated[
            str | None,
            Field(
                description=(
                    "Filter by fact type: 'world' (objective facts), 'experience' "
                    "(first-person interactions), 'observation' (consolidated entity summaries), "
                    "'opinion' (beliefs with confidence). None returns all types."
                ),
            ),
        ] = None,
        ctx: Context = None,
    ) -> str:
        """Search conversational memory using semantic + temporal retrieval.

        Returns ranked memory facts matching the query, with IDs and types.
        Uses Hindsight's TEMPR retrieval (semantic + BM25 + graph + temporal
        fusion with cross-encoder reranking).
        """
        d = get_daemon(ctx)
        backend = d.hindsight_backend
        if backend is None or not backend.ready:
            return "Error: Memory service not available."

        vis = _visibility(ctx)
        allowed = backend.visible_banks(vis)
        if bank not in allowed:
            return f"Error: Bank '{bank}' not accessible. Available: {', '.join(allowed)}"

        fact_types = [fact_type] if fact_type else None
        result = await backend.recall(
            query,
            bank=bank,
            max_tokens=max_tokens,
            fact_type=fact_types,
        )

        # Format results
        results = result.get("results") or result.get("facts") or []
        if not results:
            return "No memories found."

        formatted = _fmt_facts(results)

        entities = result.get("entities", [])
        entity_section = ""
        if entities:
            entity_lines = [f"  - {e.get('name', e)}" for e in entities[:10]]
            entity_section = "\n\nEntities:\n" + "\n".join(entity_lines)

        return f"Results:\n{formatted}{entity_section}"

    # -- memory_add (master only) -----------------------------------------

    if visibility == "master":

        @server.tool()
        async def memory_add(
            content: Annotated[
                str,
                Field(description="Text content to store as a memory fact."),
            ],
            bank: Annotated[
                str,
                Field(
                    description=("Target bank. 'parletre' = personal. 'agora' = shared."),
                ),
            ] = "parletre",
            fact_type: Annotated[
                str | None,
                Field(
                    description=(
                        "Fact classification: 'world', 'experience', 'observation', or 'opinion'. "
                        "If omitted, Hindsight classifies automatically."
                    ),
                ),
            ] = None,
            confidence: Annotated[
                float | None,
                Field(
                    description="Confidence score for opinion facts (0.0-1.0). Ignored for non-opinion types.",
                ),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Store a fact, observation, or belief in conversational memory.

            Hindsight's retain pipeline runs entity resolution and temporal
            parsing on the content. Use ``fact_type`` and ``confidence`` to
            guide classification.

            Returns the IDs and types of created memory facts.
            """
            d = get_daemon(ctx)
            backend = d.hindsight_backend
            if backend is None or not backend.ready:
                return "Error: Memory service not available."

            try:
                facts = await backend.retain(
                    content,
                    bank=bank,
                    fact_type=fact_type,
                    confidence=confidence,
                )
            except Exception as exc:
                return f"Error: {exc}"

            if not facts:
                return "Retained (no fact IDs returned)."

            lines = []
            for f in facts:
                fid = str(f.get("id", "?"))[:12]
                ft = f.get("fact_type", "world")
                lines.append(f"  [{ft}] id:{fid}")
            return "Retained:\n" + "\n".join(lines)

        @server.tool()
        async def memory_update(
            fact_id: Annotated[
                str,
                Field(description="ID of the memory fact to update (from search results)."),
            ],
            bank: Annotated[
                str,
                Field(description="Bank containing the fact."),
            ] = "parletre",
            content: Annotated[
                str | None,
                Field(description="New content text (replaces existing)."),
            ] = None,
            confidence: Annotated[
                float | None,
                Field(description="New confidence score (0.0-1.0)."),
            ] = None,
            fact_type: Annotated[
                str | None,
                Field(description="New fact type classification."),
            ] = None,
            ctx: Context = None,
        ) -> str:
            """Update an existing memory fact.

            Requires ``content`` — Hindsight replaces the old fact with a new
            one (delete + re-retain). Use ``memory_search`` first to find the
            fact ID.
            """
            d = get_daemon(ctx)
            backend = d.hindsight_backend
            if backend is None or not backend.ready:
                return "Error: Memory service not available."

            if content is None:
                return "Error: content is required for update."

            try:
                result = await backend.update(
                    fact_id,
                    bank=bank,
                    content=content,
                    confidence=confidence,
                    fact_type=fact_type,
                )
            except Exception as exc:
                return f"Error: {exc}"

            if result.get("success"):
                new_ids = result.get("new_ids", [])
                return f"Updated. Old: {fact_id[:12]}, New: {', '.join(str(i)[:12] for i in new_ids)}"
            return f"Update failed: {result.get('message', 'unknown error')}"

        @server.tool()
        async def memory_forget(
            fact_id: Annotated[
                str,
                Field(description="ID of the memory fact to delete (from search results)."),
            ],
            ctx: Context = None,
        ) -> str:
            """Delete a memory fact by ID.

            Use ``memory_search`` or ``memory_list`` first to find the fact ID.
            This permanently removes the fact from Hindsight.
            """
            d = get_daemon(ctx)
            backend = d.hindsight_backend
            if backend is None or not backend.ready:
                return "Error: Memory service not available."

            try:
                await backend.forget(fact_id)
            except Exception as exc:
                return f"Error: {exc}"

            return f"Forgotten: {fact_id[:12]}"

        @server.tool()
        async def memory_list(
            bank: Annotated[
                str,
                Field(description="Bank to list from. 'parletre' or 'agora'."),
            ] = "parletre",
            fact_type: Annotated[
                str | None,
                Field(
                    description="Filter by type: 'world', 'experience', 'observation', 'opinion'. None returns all.",
                ),
            ] = None,
            limit: Annotated[
                int,
                Field(description="Maximum number of facts to return (default 50)."),
            ] = 50,
            ctx: Context = None,
        ) -> str:
            """Browse stored memory facts with optional filtering.

            Returns a numbered list of facts with IDs and types.
            Use this for auditing memory contents or finding facts to update/forget.
            """
            d = get_daemon(ctx)
            backend = d.hindsight_backend
            if backend is None or not backend.ready:
                return "Error: Memory service not available."

            try:
                result = await backend.list_memories(
                    bank=bank,
                    fact_type=fact_type,
                    limit=limit,
                )
            except Exception as exc:
                return f"Error: {exc}"

            items = result.get("items", []) if isinstance(result, dict) else result
            if not items:
                return "No memories found."

            total = result.get("total", len(items)) if isinstance(result, dict) else len(items)
            header = f"Showing {len(items)} of {total} facts"
            if fact_type:
                header += f" (type: {fact_type})"
            return f"{header}:\n{_fmt_facts(items)}"

        @server.tool()
        async def memory_staged(
            ctx: Context = None,
        ) -> str:
            """View pending reflect changes awaiting approval.

            Shows staged memory mutations (add/update/forget) proposed during
            async reflect. Use ``clarvis checkin`` to approve or reject them.
            """
            d = get_daemon(ctx)
            store = d.staging_store
            if store is None:
                return "Error: Staging store not available."

            changes = store.list_staged()
            if not changes:
                return "No staged changes."

            lines = []
            for i, c in enumerate(changes, 1):
                parts = [f"{c.action.upper()}"]
                if c.bank:
                    parts.append(f"bank={c.bank}")
                if c.fact_type:
                    parts.append(f"type={c.fact_type}")
                if c.target_fact_id:
                    parts.append(f"target={c.target_fact_id[:12]}")
                if c.content:
                    preview = c.content[:80] + ("..." if len(c.content) > 80 else "")
                    parts.append(f'"{preview}"')
                if c.reason:
                    parts.append(f"reason: {c.reason}")
                lines.append(f"  {i}. [{c.id[:8]}] {' | '.join(parts)}")

            return f"Staged changes ({len(changes)}):\n" + "\n".join(lines)

        @server.tool()
        async def memory_approve(
            ids: Annotated[
                list[str],
                Field(description="IDs of staged changes to approve (from memory_staged output)."),
            ],
            ctx: Context = None,
        ) -> str:
            """Approve and commit staged memory changes.

            Executes each approved change against the memory backend (add/update/forget)
            and removes it from staging. Use ``memory_staged`` first to review changes.
            """
            d = get_daemon(ctx)
            store = d.staging_store
            backend = d.hindsight_backend
            if store is None or backend is None:
                return "Error: Staging or memory service not available."

            results = await store.approve(ids, backend)
            ok = sum(1 for r in results if "error" not in r)
            errs = [r for r in results if "error" in r]

            parts = [f"Approved {ok}/{len(ids)} changes."]
            if errs:
                for e in errs:
                    parts.append(f"  Error: {e['id'][:8]} -- {e['error']}")
            return "\n".join(parts)

        @server.tool()
        async def memory_reject(
            ids: Annotated[
                list[str],
                Field(description="IDs of staged changes to reject (from memory_staged output)."),
            ],
            ctx: Context = None,
        ) -> str:
            """Reject and discard staged memory changes.

            Removes the specified changes from staging without executing them.
            Use ``memory_staged`` first to review changes.
            """
            d = get_daemon(ctx)
            store = d.staging_store
            if store is None:
                return "Error: Staging store not available."

            removed = store.reject(ids)
            return f"Rejected {removed}/{len(ids)} changes."

    return server
