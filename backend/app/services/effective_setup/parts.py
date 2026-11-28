"""Shared shapes of the Effective setup response: one part per layer the agent gets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from ..knowledge_chunking.chunker import estimate_tokens

Enforcement = Literal["enforced", "guided", "guidance"]

# The admin tabs that own a part (the page's "edit" links).
PROMPT_TEXTS_TAB = "promptCatalog"
SKILLS_TAB = "skills"
TOOLS_TAB = "toolCatalog"
APPROVALS_TAB = "policies"
PART_SYSTEM_TEXTS = "system_texts"
PART_AGENT = "agent"
PART_INSTRUCTIONS = "instructions"
PART_WORKFLOW = "workflow"
PART_SKILLS = "skills"
PART_TOOLS = "tools"
PART_APPROVALS = "approvals"

# Budget groups shown as one bar: platform + agent, instructions + workflow, skills.
BUDGET_GROUPS = (
    ("platform_agent", "Platform + agent", (PART_SYSTEM_TEXTS, PART_AGENT)),
    ("instructions_workflow", "Instructions + workflow", (PART_INSTRUCTIONS, PART_WORKFLOW)),
    ("skills", "Skills", (PART_SKILLS,)),
)


@dataclass(slots=True)
class SetupPart:
    id: str
    title: str
    source_label: str
    source_tab: str = ""
    version: str = ""
    enforced: Enforcement = "enforced"
    tokens: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "source": {"label": self.source_label, "tab": self.source_tab or None},
            "version": self.version or None,
            "enforced": self.enforced,
            "tokens": self.tokens,
            "details": self.details,
        }


def tokens_of(text: str | None) -> int:
    clean = str(text or "").strip()
    return estimate_tokens(clean) if clean else 0


def budget(parts: list[SetupPart], *, limit: int) -> dict[str, Any]:
    by_id = {part.id: part.tokens for part in parts}
    groups = [
        {"key": key, "label": label, "tokens": sum(by_id.get(part_id, 0) for part_id in members)}
        for key, label, members in BUDGET_GROUPS
    ]
    return {"total": sum(by_id.values()), "limit": int(limit or 0), "groups": groups}


__all__ = [
    "BUDGET_GROUPS",
    "PART_AGENT",
    "PART_APPROVALS",
    "PART_INSTRUCTIONS",
    "PART_SKILLS",
    "PART_SYSTEM_TEXTS",
    "PART_TOOLS",
    "PART_WORKFLOW",
    "Enforcement",
    "SetupPart",
    "budget",
    "tokens_of",
]
