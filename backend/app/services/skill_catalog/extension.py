"""The platform extension of a skill version: what Octryx adds next to the Agent Skills bundle.

``tools`` lists the tools a skill needs per surface (platform chat tool names; Claude Code permission patterns
such as ``Bash(terraform validate *)``). They are **never** delivered as ``allowed-tools``: they only feed the
readiness view and the chat's required-tools check. ``safety_rules`` and ``output_contract`` are rendered into the
delivered body; ``approval_rules`` and the executor fields stay chat-only with unchanged semantics;
``allowed_roles`` is resolved before delivery (no role, no skill). ``card_content`` optionally overrides the
derived card (description + section outline).
"""

from __future__ import annotations

import re
from typing import Any

SURFACE_PLATFORM_CHAT = "platform_chat"
SURFACE_OCTRYX_CLAUDE = "octryx_claude"
SURFACES = (SURFACE_PLATFORM_CHAT, SURFACE_OCTRYX_CLAUDE)

MAX_RULES = 50
MAX_RULE_CHARS = 500
MAX_TOOLS = 50
MAX_TOOL_CHARS = 200
MAX_CARD_CHARS = 4000

_HEADING = re.compile(r"^(#{1,3})\s+(.+?)\s*#*\s*$")


def _strings(value: Any, *, limit: int, chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    seen: list[str] = []
    for item in value:
        text = str(item or "").strip()[:chars]
        if text and text not in seen:
            seen.append(text)
    return seen[:limit]


def _tools(value: Any) -> dict[str, dict[str, list[str]]]:
    raw = value if isinstance(value, dict) else {}
    tools: dict[str, dict[str, list[str]]] = {}
    for surface in SURFACES:
        entry = raw.get(surface) if isinstance(raw.get(surface), dict) else {}
        tools[surface] = {
            "required": _strings(entry.get("required"), limit=MAX_TOOLS, chars=MAX_TOOL_CHARS),
            "optional": _strings(entry.get("optional"), limit=MAX_TOOLS, chars=MAX_TOOL_CHARS),
        }
    return tools


def normalize_extension(value: Any) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    output_contract = raw.get("output_contract")
    approval_rules = raw.get("approval_rules")
    executor_config = raw.get("executor_config")
    parameters = raw.get("parameters")
    return {
        "tools": _tools(raw.get("tools")),
        "output_contract": dict(output_contract) if isinstance(output_contract, dict) else {},
        "safety_rules": _strings(raw.get("safety_rules"), limit=MAX_RULES, chars=MAX_RULE_CHARS),
        "approval_rules": dict(approval_rules) if isinstance(approval_rules, dict) else {},
        "allowed_roles": sorted({item.lower() for item in _strings(raw.get("allowed_roles"), limit=50, chars=80)}),
        "executor_type": str(raw.get("executor_type") or "llm_interpret")[:50],
        "executor_config": dict(executor_config) if isinstance(executor_config, dict) else None,
        "parameters": dict(parameters) if isinstance(parameters, dict) else None,
        "card_content": str(raw.get("card_content") or "")[:MAX_CARD_CHARS],
        "requires_approval": bool(raw.get("requires_approval")),
    }


def outline(body: str, *, limit: int = 12) -> list[str]:
    """The level 1-3 headings of a Markdown body, outside fenced code blocks."""
    headings: list[str] = []
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        match = _HEADING.match(line)
        if match:
            headings.append(f"{'  ' * (len(match.group(1)) - 1)}- {match.group(2)}")
    return headings[:limit]


def card_text(description: str, body: str, extension: dict[str, Any]) -> str:
    override = str(extension.get("card_content") or "").strip()
    if override:
        return override
    sections = outline(body)
    return description if not sections else f"{description}\n\nSections:\n" + "\n".join(sections)


def delivered_body(body: str, extension: dict[str, Any]) -> str:
    """The body plus the catalog's output contract and safety rules."""
    parts = [body.rstrip("\n")]
    contract = extension.get("output_contract") or {}
    if contract:
        lines = [f"- **{key}**: {value}" for key, value in sorted(contract.items())]
        parts.append("## Output\n\n" + "\n".join(lines))
    rules = extension.get("safety_rules") or []
    if rules:
        parts.append("## Safety rules\n\n" + "\n".join(f"- {rule}" for rule in rules))
    return "\n\n".join(parts) + "\n"


def token_cost(text: str) -> int:
    """A deterministic estimate (4 characters per token), shown in the catalog; never a decision input."""
    return (len(text) + 3) // 4


__all__ = [
    "SURFACES",
    "SURFACE_OCTRYX_CLAUDE",
    "SURFACE_PLATFORM_CHAT",
    "card_text",
    "delivered_body",
    "normalize_extension",
    "outline",
    "token_cost",
]
