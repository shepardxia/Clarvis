"""Memory MCP sub-server — mounted onto the main Clarvis server.

Exposes 4 unified memory tools (search, recall, add, forget) that delegate to
the daemon's dual-backend MemoryService (Graphiti + memU).

All tools return natural language strings for agent readability.
Dataset descriptions in tool schemas are auto-generated from config.
"""

import json
import logging
from pathlib import Path
from typing import Annotated

from fastmcp import Context, FastMCP
from pydantic import Field

from ._helpers import get_daemon_service, make_lifespan

logger = logging.getLogger(__name__)

_TRANSCRIPT_PATH = Path.home() / ".clarvis" / "channels" / "transcript.jsonl"


def _visibility(ctx: Context) -> str:
    return ctx.fastmcp._lifespan_result["visibility"]


def _build_dataset_description(
    dataset_configs: dict,
    default_name: str,
) -> tuple[str, str]:
    """Build a dataset Field description and default from config.

    Returns (description_string, default_dataset_name).
    """
    parts = ["Target dataset."]
    for name, cfg in dataset_configs.items():
        label = f"'{name}'"
        vis = "Clarvis only" if cfg.visibility == "master" else "all agents"
        desc = cfg.description or vis
        parts.append(f"{label} ({desc})")
    parts.append(
        "Clarvis (home agent) has access to all datasets; "
        "Clarvisus (channel agents) can only access datasets with 'all' visibility."
    )
    # Pick the first "all"-visibility dataset as default, or fall back
    default = default_name
    for name, cfg in dataset_configs.items():
        if cfg.visibility == "all":
            default = name
            break
    return " ".join(parts), default


def _read_recent_transcript(
    path: Path,
    max_lines: int = 20,
) -> list[dict[str, str]]:
    """Read last *max_lines* entries from a JSONL transcript file.

    Returns list of ``{"role": "user"|"assistant", "content": "..."}``.
    Silently returns empty list on missing file or parse errors.
    """
    if not path.is_file():
        return []
    messages: list[dict[str, str]] = []
    try:
        lines = path.read_text().strip().splitlines()
        for line in lines[-max_lines:]:
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            # Transcript format: {"sender": "...", "content": "...", ...}
            sender = entry.get("sender", "")
            content = entry.get("content", "")
            if not content:
                continue
            role = "assistant" if sender == "clarvis" else "user"
            messages.append({"role": role, "content": content[:2000]})
    except Exception:
        logger.debug("Failed to read transcript at %s", path, exc_info=True)
    return messages


def _format_recall_result(result: dict) -> str:
    """Format a structured recall result dict into readable text."""
    if "error" in result:
        return f"Error: {result['error']}"

    sections: list[str] = []

    # Categories
    categories = result.get("categories", [])
    if categories:
        lines = ["## Categories"]
        for cat in categories:
            if isinstance(cat, dict):
                name = cat.get("name", "unknown")
                summary = cat.get("summary", "")
                lines.append(f"- **{name}**: {summary}" if summary else f"- **{name}**")
            else:
                lines.append(f"- {cat}")
        sections.append("\n".join(lines))

    # Items
    items = result.get("items", [])
    if items:
        lines = ["## Memory Items"]
        for i, item in enumerate(items, 1):
            if isinstance(item, dict):
                text = item.get("summary") or item.get("text") or str(item)
                mtype = item.get("memory_type", "")
                tag = f" [{mtype}]" if mtype else ""
                lines.append(f"  {i}.{tag} {text}")
            else:
                lines.append(f"  {i}. {item}")
        sections.append("\n".join(lines))

    # Graphiti facts
    facts = result.get("graphiti_facts", [])
    if facts:
        lines = ["## Knowledge Graph Facts"]
        for i, fact in enumerate(facts, 1):
            if isinstance(fact, dict):
                text = fact.get("fact") or fact.get("text") or str(fact)
            else:
                text = str(fact)
            lines.append(f"  {i}. {text}")
        sections.append("\n".join(lines))

    # Next step query
    nsq = result.get("next_step_query")
    if nsq:
        sections.append(f"**Suggested follow-up:** {nsq}")

    if not sections:
        return "No memories found."
    return "\n\n".join(sections)


def create_memory_server(daemon, visibility: str = "master"):
    """Create the memory MCP sub-server.

    Args:
        daemon: CentralHubDaemon instance.
        visibility: Access level for dataset filtering.
            ``"master"`` sees all datasets.
            ``"all"`` sees only shared datasets.
    """
    # Build dynamic dataset description from config
    ds_configs = {}
    if daemon.memory_service:
        ds_configs = daemon.memory_service._dataset_configs
    ds_desc, ds_default = _build_dataset_description(ds_configs, "agora")

    server = FastMCP("Memory", lifespan=make_lifespan(daemon, visibility=visibility))

    @server.tool()
    async def memory_search(
        query: Annotated[
            str,
            Field(description="Natural language query to search memory."),
        ],
        top_k: Annotated[
            int,
            Field(description="Maximum number of results to return."),
        ] = 10,
        ctx: Context = None,
    ) -> str:
        """Search the knowledge graph and categorized memory.

        Queries both Graphiti (temporal facts, entities, relationships) and
        memU (categorized personal memory). Results are merged and numbered.
        Datasets searched depend on your access level — Clarvis sees all
        datasets; Clarvisus sees only shared ones.
        """
        svc, err = get_daemon_service(ctx, "memory_service", "Memory service")
        if err:
            return err
        vis = _visibility(ctx)
        results = await svc.search(query, visibility=vis, top_k=top_k)
        if not results:
            return "No results found."
        lines = []
        for i, item in enumerate(results, 1):
            if isinstance(item, dict):
                text = item.get("fact") or item.get("text") or str(item)
            else:
                text = str(item)
            lines.append(f"  {i}. {text}")
        return "\n".join(lines)

    @server.tool()
    async def memory_recall(
        method: Annotated[
            str,
            Field(description="Retrieval method: 'rag' (fast, default) or 'llm' (deep reasoning)."),
        ] = "rag",
        ctx: Context = None,
    ) -> str:
        """Recall relevant memories using conversation context.

        Reads the last 20 turns from the channel transcript and uses them
        as context for tiered memory retrieval (categories → items → resources).
        Returns structured results from both memU and Graphiti.

        Call this proactively at the start of a conversation or when you
        need to recall what you know about the user or topic.
        """
        svc, err = get_daemon_service(ctx, "memory_service", "Memory service")
        if err:
            return err
        vis = _visibility(ctx)

        # Read recent transcript for context
        context_messages = _read_recent_transcript(_TRANSCRIPT_PATH, max_lines=20)

        # Build query from last user message, or use a generic recall query
        query = "Recall relevant memories for this conversation."
        for msg in reversed(context_messages):
            if msg.get("role") == "user":
                query = msg["content"]
                break

        result = await svc.recall(
            query,
            visibility=vis,
            context_messages=context_messages,
            method=method,
        )

        return _format_recall_result(result)

    @server.tool()
    async def memory_add(
        data: Annotated[
            str | None,
            Field(description="Text content to store — facts, observations, or longer passages."),
        ] = None,
        file_path: Annotated[
            str | None,
            Field(description="Absolute path to a file whose contents should be stored."),
        ] = None,
        dataset: Annotated[
            str,
            Field(description=ds_desc),
        ] = ds_default,
        ctx: Context = None,
    ) -> str:
        """Store a fact, observation, or file in long-term memory.

        Provide exactly one of ``data`` (text) or ``file_path``.
        Content is indexed in both the knowledge graph (Graphiti) and
        categorized memory (memU).
        """
        svc, err = get_daemon_service(ctx, "memory_service", "Memory service")
        if err:
            return err
        vis = _visibility(ctx)

        # Validate exactly one input
        if bool(data) == bool(file_path):
            return "Error: Provide exactly one of 'data' or 'file_path'."

        # Validate dataset access
        visible = svc._memu.visible_datasets(visibility=vis)
        if dataset not in visible:
            return f"Error: Dataset '{dataset}' not accessible. Available: {', '.join(sorted(visible))}"

        # Read file if needed
        if file_path:
            from pathlib import Path

            p = Path(file_path)
            if not p.is_file():
                return f"Error: File not found: {file_path}"
            content = p.read_text()
        else:
            content = data

        result = await svc.add(content, dataset=dataset)
        if isinstance(result, dict) and "error" in result:
            return f"Error: {result['error']}"
        return f"Added to {dataset}."

    @server.tool()
    async def memory_forget(
        item_id: Annotated[
            str,
            Field(description="ID of the memory item to forget (from search results)."),
        ],
        dataset: Annotated[
            str,
            Field(description=ds_desc),
        ] = ds_default,
        ctx: Context = None,
    ) -> str:
        """Delete a memory item from categorized memory.

        Use ``memory_search`` first to find the item ID, then call this
        to remove it. Only removes from memU (categorized memory); Graphiti
        knowledge graph nodes are managed separately.
        """
        svc, err = get_daemon_service(ctx, "memory_service", "Memory service")
        if err:
            return err
        vis = _visibility(ctx)

        # Validate dataset access
        visible = svc._memu.visible_datasets(visibility=vis)
        if dataset not in visible:
            return f"Error: Dataset '{dataset}' not accessible. Available: {', '.join(sorted(visible))}"

        result = await svc.forget(item_id, dataset=dataset)
        if isinstance(result, dict) and "error" in result:
            return f"Error: {result['error']}"
        if isinstance(result, dict) and "status" in result:
            return result["status"]
        return f"Forgotten item {item_id} from {dataset}."

    return server
