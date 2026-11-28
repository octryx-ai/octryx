"""Dropping the prompt sections whose tools a chat request does not send in full."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

# Prompt sections that only matter when a tool that uses them is sent (the chat defers skill_search and
# run_cli_command; without this every call would carry their ~0.8k characters of guidance).
_SECTION_TOOLS: dict[str, frozenset[str]] = {
    "## Skill Discovery": frozenset({"skill_search", "skill_get"}),
    "## Runtime Environment": frozenset({
        "run_cli_command", "run_kubectl", "run_saved_python_script", "run_test_suite", "run_validation_commands",
        "run_playbook", "run_sast_suite", "run_openrewrite_recipe", "get_system_context",
    }),
}


def _without_section(text: str, heading: str) -> str:
    start = text.find(heading)
    if start < 0 or (start and text[start - 1] != "\n"):
        return text
    # A section ends at the next heading or blank line: notes appended to the system message (a confirmed write plan,
    # the role note) follow after a blank line and must stay (cutting to the next heading would drop them).
    ends = [found for marker in ("\n## ", "\n\n") if (found := text.find(marker, start + len(heading))) >= 0]
    end = min(ends) if ends else -1
    return text[:start].rstrip("\n") + ("\n\n" + text[end:].lstrip("\n") if end >= 0 else "")


def drop_unused_prompt_sections(messages: list[dict[str, Any]], sent_tool_names: Iterable[str]) -> list[dict[str, Any]]:
    """The request messages without the sections whose tools this request does not send in full."""
    sent = set(sent_tool_names)
    unused = [heading for heading, tools in _SECTION_TOOLS.items() if not tools & sent]
    if not unused:
        return messages
    result = []
    for message in messages:
        content = message.get("content")
        if message.get("role") == "system" and isinstance(content, str) and any(h in content for h in unused):
            for heading in unused:
                content = _without_section(content, heading)
            message = {**message, "content": content}
        result.append(message)
    return result
