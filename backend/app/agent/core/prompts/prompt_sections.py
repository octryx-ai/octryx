"""Shared prompt section assembly helpers: the agent sections of the stable part and the dynamic context."""

from __future__ import annotations

from typing import Any

from .agent_blueprint import agent_blueprint_section, agent_instruction_priority_section, agent_reply_format_section
from .prompt_parts import CatalogText, PromptSection, authored_section, catalog_section, rendered, untrusted_section


def stable_agent_sections(
    *,
    thinking: CatalogText | None = None,
    agent_definition: dict[str, Any] | None = None,
    personality: str = "",
    skills: CatalogText | None = None,
) -> list[PromptSection]:
    """Thinking mode, the selected agent (authored), the communication preferences (untrusted), precedence, skills.

    The catalog-rendered sections (thinking mode, precedence, skill discovery) take the trust of their source.
    """
    sections: list[PromptSection] = []
    if thinking is not None and thinking.text:
        sections.append(catalog_section(thinking))
    blueprint = agent_blueprint_section(agent_definition)
    if blueprint:
        sections.append(authored_section(blueprint))
    reply_format = agent_reply_format_section(agent_definition)
    if reply_format:
        sections.append(authored_section(reply_format))
    if personality:
        # The person's own preference text rides in these lines.
        sections.append(untrusted_section(f"\n## Communication Preferences\n{personality}"))
    # After the style preferences in the same (stable) call: the selected agent's task and output
    # requirements are the last word on format; ordinary chat (no agent) renders nothing here.
    priority = rendered(lambda: agent_instruction_priority_section(agent_definition))
    if priority.text:
        sections.append(catalog_section(priority))
    if skills is not None and skills.text:
        sections.append(catalog_section(CatalogText(f"\n## Skill Discovery\n{skills.text}", skills.sources)))
    return sections


def dynamic_context_sections(
    *,
    entity_context: str = "",
    context_compaction: str = "",
    checkpoint_context: str = "",
    evidence_grounding: str = "",
    repo_microagents: str = "",
    repo_knowledge: str = "",
    memory: str = "",
) -> list[str]:
    sections: list[str] = []
    if entity_context:
        sections.append(f"\n## Current Entities\n{entity_context}")
    if context_compaction:
        sections.append(f"\n## Compacted Runtime Context\n{context_compaction}")
    if checkpoint_context:
        sections.append(f"\n## Context Checkpoint\n{checkpoint_context}")
    if evidence_grounding:
        sections.append(f"\n{evidence_grounding}")
    if repo_microagents:
        sections.append(f"\n{repo_microagents}")
    if repo_knowledge:
        sections.append(f"\n{repo_knowledge}")
    if memory:
        sections.append(f"\n## Memory\n{memory}")
    return sections
