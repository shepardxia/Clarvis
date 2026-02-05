"""Tool classification for semantic status mapping.

Maps Claude Code tool names to status strings based on tool
category sets and keyword heuristics for MCP tools.
"""

from __future__ import annotations


# Explicit tool category sets
READING_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "LS", "NotebookRead"}
WRITING_TOOLS = {"Write", "Edit", "NotebookEdit"}
EXECUTING_TOOLS = {"Bash", "TodoWrite", "TodoRead"}
THINKING_TOOLS = {"Task", "EnterPlanMode", "ExitPlanMode"}
AWAITING_TOOLS = {"AskUserQuestion"}

# Keywords for MCP tool heuristic classification
READING_KEYWORDS = {"read", "get", "list", "find", "search", "fetch", "query", "inspect", "browse", "view"}
WRITING_KEYWORDS = {"write", "create", "edit", "replace", "insert", "delete", "update", "add", "remove", "set"}
EXECUTING_KEYWORDS = {"execute", "run", "shell", "browser", "click", "navigate", "type", "press", "play", "pause"}


def classify_tool(tool_name: str) -> str:
    """Classify a tool into a semantic status based on its name.

    Checks explicit tool sets first, then falls back to keyword-based
    heuristics for MCP tools (prefixed with ``mcp__``).

    Returns:
        A status string (e.g. "reading", "writing", "executing").
    """
    # Explicit matches first (highest priority)
    if tool_name in READING_TOOLS:
        return "reading"
    if tool_name in WRITING_TOOLS:
        return "writing"
    if tool_name in EXECUTING_TOOLS:
        return "executing"
    if tool_name in THINKING_TOOLS:
        return "thinking"
    if tool_name in AWAITING_TOOLS:
        return "awaiting"

    # MCP tool heuristics (pattern matching)
    if tool_name.startswith("mcp__"):
        lower = tool_name.lower()
        # Check keywords in order of specificity
        if any(kw in lower for kw in WRITING_KEYWORDS):
            return "writing"
        if any(kw in lower for kw in EXECUTING_KEYWORDS):
            return "executing"
        if any(kw in lower for kw in READING_KEYWORDS):
            return "reading"

    # Default for unknown tools
    return "running"
