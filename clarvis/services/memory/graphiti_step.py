"""GraphitiStep — memU pipeline step that syncs extracted items to Graphiti.

Inserted after ``categorize_items`` in the ``memorize()`` pipeline so that
Graphiti receives pre-extracted items instead of re-processing raw text,
eliminating redundant LLM extraction costs.
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def make_graphiti_step(graphiti_backend: Any) -> Any:
    """Create a pipeline step that feeds extracted items to Graphiti.

    Args:
        graphiti_backend: A started :class:`GraphitiBackend` instance.

    Returns:
        A :class:`~memu.workflow.step.WorkflowStep` dataclass.
    """
    from memu.workflow.step import WorkflowStep

    async def _handler(state: dict, context: Any) -> dict:
        items = state.get("items", [])
        user = state.get("user", {})
        dataset = user.get("dataset", "agora") if isinstance(user, dict) else "agora"

        for item in items:
            summary = getattr(item, "summary", None) or str(item)
            memory_type = getattr(item, "memory_type", "knowledge")
            try:
                await graphiti_backend.add_episode(
                    text=summary,
                    dataset=dataset,
                    name=memory_type,
                )
            except Exception:
                logger.exception(
                    "GraphitiStep: failed to sync item (type=%s, dataset=%s)",
                    memory_type,
                    dataset,
                )
        return state

    return WorkflowStep(
        step_id="graphiti_sync",
        role="sync",
        handler=_handler,
        description="Sync extracted items to Graphiti knowledge graph",
        requires={"items"},
        produces=set(),
    )
