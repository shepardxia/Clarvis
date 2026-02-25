"""Tool name → semantic status classification."""
# --- Tool classification ---

READING_TOOLS = {"Read", "Grep", "Glob", "WebFetch", "WebSearch", "LS", "NotebookRead"}
WRITING_TOOLS = {"Write", "Edit", "NotebookEdit"}
EXECUTING_TOOLS = {"Bash", "TodoWrite", "TodoRead"}
THINKING_TOOLS = {"Task", "EnterPlanMode", "ExitPlanMode"}
AWAITING_TOOLS = {"AskUserQuestion"}

READING_KEYWORDS = {"read", "get", "list", "find", "search", "fetch", "query", "inspect", "browse", "view"}
WRITING_KEYWORDS = {"write", "create", "edit", "replace", "insert", "delete", "update", "add", "remove", "set"}
EXECUTING_KEYWORDS = {"execute", "run", "shell", "browser", "click", "navigate", "type", "press", "play", "pause"}


def classify_tool(tool_name: str) -> str:
    """Classify a tool into a semantic status based on its name."""
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

    if tool_name.startswith("mcp__"):
        lower = tool_name.lower()
        if any(kw in lower for kw in WRITING_KEYWORDS):
            return "writing"
        if any(kw in lower for kw in EXECUTING_KEYWORDS):
            return "executing"
        if any(kw in lower for kw in READING_KEYWORDS):
            return "reading"

    return "running"
