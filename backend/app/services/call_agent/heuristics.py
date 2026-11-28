"""Text heuristics of the CallAgent: planning-answer parsing, parameter guessing, result summaries."""

from __future__ import annotations

import re
from typing import Any

_RESPONSE_INSTRUCTION = (
    "Give a clear, concise answer that can be spoken aloud as is. "
    "Summarize the most important points. "
    "If you have a suggestion or a question, work it in naturally."
)


def planning_messages(system_prompt: str | None, context: str, enabled_tools: set[str]) -> list[dict]:
    return [
        {"role": "system", "content": system_prompt or ""},
        {
            "role": "user",
            "content": (
                f"{context}\n\n"
                "Analyze the user's request. "
                "Which tools do you need to answer the question? "
                "Answer with a list of tool names (one per line), "
                "or 'NONE' if no tools are needed.\n"
                f"Available tools: {', '.join(sorted(enabled_tools))}"
            ),
        },
    ]


def final_messages(system_prompt: str | None, context: str, tool_context: str) -> list[dict]:
    if tool_context:
        user_content = f"{context}\n\nTool results:\n{tool_context}\n\n{_RESPONSE_INSTRUCTION}"
    else:
        user_content = f"{context}\n\n{_RESPONSE_INSTRUCTION}"

    return [
        {"role": "system", "content": system_prompt or ""},
        {"role": "user", "content": user_content},
    ]


def format_tool_results(tool_results: list[dict]) -> str:
    lines = []
    for item in tool_results:
        tool_name = item.get("tool", "unknown")
        result = item.get("result", {})

        if "error" in result:
            lines.append(f"[{tool_name}] ERROR: {result['error']}")
        elif isinstance(result, dict):
            # Try to extract useful info
            summary = summarize_result(result)
            lines.append(f"[{tool_name}]\n{summary}")
        else:
            lines.append(f"[{tool_name}]\n{str(result)}")

    return "\n\n".join(lines)


def summarize_result(result: dict, max_len: int = 1500) -> str:
    # Common useful fields
    important_keys = {"title", "name", "status", "summary", "description", "result", "count", "items"}

    # Try to extract key info
    summary_parts = []
    for key in important_keys:
        if key in result:
            val = result[key]
            if isinstance(val, (list, dict)):
                val = str(val)[:200]
            summary_parts.append(f"{key}: {val}")

    if summary_parts:
        text = "\n".join(summary_parts)
    else:
        # Fallback: truncate dict
        text = str(result)[:max_len]

    if len(text) > max_len:
        text = text[:max_len] + "..."

    return text


def detect_follow_up(response: str) -> str | None:
    # Look for question marks at the end or "?" followed by suggestion
    # Simple heuristic: the response ends with "?" or asks the caller a direct question
    patterns = [
        r"\?\s*$",  # ends with ?
        r"what is the",
        r"how is the",
        r"could you",
        r"can we",
        r"would you",
        r"should i",
    ]

    response_lower = response.lower()
    for pattern in patterns:
        if re.search(pattern, response_lower):
            # Extract the question
            sentences = re.split(r"[.!?]", response)
            for sent in reversed(sentences):
                sent = sent.strip()
                if any(re.search(p, sent.lower()) for p in patterns) or sent.endswith("?"):
                    return sent
            return response

    return None


def extract_tool_names(text: str) -> list[str]:
    lines = text.strip().split("\n")
    tools = []

    for line in lines:
        line = line.strip()
        # Remove common prefixes
        for prefix in ["- ", "* ", "1. ", "2. ", "3. ", "• "]:
            if line.startswith(prefix):
                line = line[len(prefix):]

        line = line.strip()

        # Skip "NONE", empty lines, and non-tool text
        if line.upper() in ("NONE", "NO TOOLS", ""):
            continue
        if len(line) > 50:  # Too long to be a tool name
            continue
        if not any(c.islower() for c in line):  # ALL CAPS = not a tool name
            continue

        # Check if it looks like a tool name (category.tool format)
        if "." in line or "_" in line:
            tools.append(line)

    return tools


def extract_params(tool_name: str, user_message: str) -> dict:
    # This is a simple implementation
    # A more sophisticated version would use LLM to extract params
    params: dict[str, Any] = {}

    # Common patterns
    if "search" in tool_name or "query" in tool_name:
        # Extract query from user message
        # Remove common leading phrases
        query = user_message
        for prefix in ["hey octryx,", "hey octryx ", "octryx,", "octryx "]:
            if query.lower().startswith(prefix.lower()):
                query = query[len(prefix):]
                break
        params["query"] = query.strip()
        params["limit"] = 5

    if "get_issue" in tool_name or "get_issue" in tool_name:
        # Try to extract issue ID
        issue_match = re.search(r"([A-Z]+-\d+)", user_message)
        if issue_match:
            params["issue_id"] = issue_match.group(1)

    return params
