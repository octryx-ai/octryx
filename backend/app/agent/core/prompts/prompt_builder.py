"""Prompt building helpers for the agent engine."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ....models import Personality
from ....services.prompt_catalog import render_prompt, rendered_prompts
from .prompt_defaults import resolve_prompt_thinking_mode
from .prompt_parts import (
    CatalogText,
    PromptSection,
    SystemPromptParts,
    authored_section,
    catalog_section,
    keyed,
    rendered,
)
from .prompt_runtime_environment import build_runtime_environment_section
from .prompt_sections import dynamic_context_sections, stable_agent_sections
from .prompt_templates import render_system_prompt_template, resolve_system_prompt_variant

#: The catalog key the ``skills`` text is rendered from (``build_skill_discovery_prompt``, run preparation).
SKILL_DISCOVERY_KEY = "system.skill_discovery"


def _untrusted_fence_line() -> str:
    """Knowledge results, tickets, pages and alerts reach the model fenced
    (``content_security/knowledge_fence``); one line in every variant says what a fence means."""
    return render_prompt("system.untrusted_fence")


def _dynamic_context_prompt_section() -> str:
    return "\n" + render_prompt("system.dynamic_context_prompts")


_MODE_BEHAVIOR_CAPABILITIES = frozenset({"diagnosis", "change", "plan", "admin"})
# Variants whose template stands without the mode definition and, for bounded_evidence, without any context.
_NARROW_PROMPT_VARIANTS = frozenset({"bounded_evidence", "minimal"})


def _mode_behavior_line(capability_type: str) -> str:
    capability = capability_type if capability_type in _MODE_BEHAVIOR_CAPABILITIES else "diagnosis"
    return render_prompt(f"system.mode_behavior.{capability}")


def build_system_prompt(
    agent_type: str,
    agent_mode: Any,
    personality: str,
    memory: str,
    skills: str,
    entity_context: str = "",
    context_compaction: str = "",
    checkpoint_context: str = "",
    evidence_grounding: str = "",
    repo_microagents: str = "",
    repo_knowledge: str = "",
    system_context: dict[str, object] | None = None,
    thinking_level: str | None = None,
    agent_definition: dict | None = None,
    prompt_variant: str = "full",
    prompt_variant_routing: Mapping[str, str] | None = None,
) -> str:
    return build_system_prompt_parts(
        agent_type=agent_type,
        agent_mode=agent_mode,
        personality=personality,
        memory=memory,
        skills=skills,
        entity_context=entity_context,
        context_compaction=context_compaction,
        checkpoint_context=checkpoint_context,
        evidence_grounding=evidence_grounding,
        repo_microagents=repo_microagents,
        repo_knowledge=repo_knowledge,
        system_context=system_context,
        thinking_level=thinking_level,
        agent_definition=agent_definition,
        prompt_variant=prompt_variant,
        prompt_variant_routing=prompt_variant_routing,
    ).combined


def _mode_definition_section(
    resolved_prompt_variant: str,
    *,
    mode_key: str,
    mode_name: str,
    capability_type: str,
    mode_behavior_line: str,
    mode_instructions: str,
) -> str:
    # Only rendered where it is injected, so the turn's prompt record names exactly what the model saw.
    if resolved_prompt_variant == "bounded_evidence":
        return ""
    section = "\n" + render_prompt(
        "system.mode_definition",
        mode_key=mode_key,
        mode_name=mode_name,
        capability_type=capability_type,
        mode_behavior_line=mode_behavior_line,
    )
    if mode_instructions:
        section += "\n" + render_prompt("system.mode_instructions_line", mode_instructions=mode_instructions)
    return section


def _thinking_text(thinking_level: str | None, resolved_prompt_variant: str) -> CatalogText | None:
    with rendered_prompts() as used:
        thinking_mode = resolve_prompt_thinking_mode(thinking_level, prompt_variant=resolved_prompt_variant)
    if not thinking_mode:
        return None
    selected_mode, thinking_instruction = thinking_mode
    return CatalogText(f"\n## Thinking Mode\n- Selected mode: {selected_mode}\n- Instruction: {thinking_instruction}",
                       tuple(used))


def _stable_sections(
    resolved_prompt_variant: str,
    *,
    mode_name: str,
    mode_behavior_line: CatalogText,
    prompt_variant_routing: Mapping[str, str] | None,
    mode_definition_section: CatalogText,
    workflow_catalog_section: str,
    thinking_level: str | None,
    agent_definition: dict | None,
    personality: str,
    skills: str,
) -> list[PromptSection]:
    """The cacheable part of the prompt; bounded_evidence keeps only its template, fence and catalog.

    The selected agent's blueprint rides in the stable part of every variant the plan gives it,
    except bounded_evidence, whose deliberately narrow contract carries no blueprint. The workflow catalog
    lists Workspace workflows (authored text); the catalog-rendered sections (templates, mode definition, fence)
    take the trust of their source (``prompt_parts.catalog_section``).
    """
    narrow_variant = resolved_prompt_variant in _NARROW_PROMPT_VARIANTS
    stable_sections = [
        catalog_section(rendered(lambda: render_system_prompt_template(
            resolved_prompt_variant,
            mode_name=mode_name,
            mode_behavior_line=mode_behavior_line.text,
            prompt_variant_routing=prompt_variant_routing,
        ), mode_behavior_line)),
        catalog_section(rendered(_untrusted_fence_line)),
    ]
    if narrow_variant and workflow_catalog_section:
        stable_sections.append(authored_section(workflow_catalog_section))
    if resolved_prompt_variant == "bounded_evidence":
        return stable_sections
    stable_sections.append(catalog_section(mode_definition_section))
    stable_sections.append(catalog_section(rendered(_dynamic_context_prompt_section)))
    if not narrow_variant and workflow_catalog_section:
        stable_sections.append(authored_section(workflow_catalog_section))
    stable_sections += stable_agent_sections(
        thinking=_thinking_text(thinking_level, resolved_prompt_variant),
        agent_definition=agent_definition,
        personality=personality,
        skills=keyed(skills, (SKILL_DISCOVERY_KEY,)) if skills else None,
    )
    return stable_sections


def _dynamic_sections(
    resolved_prompt_variant: str,
    *,
    system_context: dict[str, object] | None,
    entity_context: str,
    context_compaction: str,
    checkpoint_context: str,
    evidence_grounding: str,
    repo_microagents: str,
    repo_knowledge: str,
    memory: str,
) -> list[str]:
    """The per-turn part of the prompt; bounded_evidence has none and minimal adds memory only when grounded."""
    dynamic_sections: list[str] = []
    if resolved_prompt_variant == "bounded_evidence":
        return dynamic_sections
    if resolved_prompt_variant not in {*_NARROW_PROMPT_VARIANTS, "summary", "admin"}:
        runtime_environment_section = build_runtime_environment_section(system_context)
        if runtime_environment_section:
            dynamic_sections.append(runtime_environment_section)
    dynamic_sections += dynamic_context_sections(
        entity_context=entity_context,
        context_compaction=context_compaction,
        checkpoint_context=checkpoint_context,
        evidence_grounding=evidence_grounding,
        repo_microagents=repo_microagents,
        repo_knowledge=repo_knowledge,
        memory=memory if resolved_prompt_variant != "minimal" or evidence_grounding else "",
    )
    return dynamic_sections


def build_system_prompt_parts(
    agent_type: str,
    agent_mode: Any,
    personality: str,
    memory: str,
    skills: str,
    entity_context: str = "",
    context_compaction: str = "",
    checkpoint_context: str = "",
    evidence_grounding: str = "",
    repo_microagents: str = "",
    repo_knowledge: str = "",
    system_context: dict[str, object] | None = None,
    thinking_level: str | None = None,
    agent_definition: dict | None = None,
    prompt_variant: str = "full",
    prompt_variant_routing: Mapping[str, str] | None = None,
    workflow_catalog: str = "",
) -> SystemPromptParts:
    capability_type = (agent_mode.capability_type or "diagnosis").strip().lower()
    mode_name = agent_mode.name or agent_type
    resolved_prompt_variant = resolve_system_prompt_variant(
        prompt_variant, prompt_variant_routing=prompt_variant_routing
    )
    mode_behavior_line = rendered(lambda: _mode_behavior_line(capability_type))
    mode_definition_section = rendered(lambda: _mode_definition_section(
        resolved_prompt_variant, mode_key=agent_mode.key or agent_type, mode_name=mode_name,
        capability_type=capability_type, mode_behavior_line=mode_behavior_line.text,
        mode_instructions=(agent_mode.prompt_instructions or "").strip(),
    ), mode_behavior_line)
    # Model-side workflow catalog: visible in every mode/variant so the model can select a governed
    # workflow via select_workflow (progressive disclosure; stable section, cache-friendly).
    workflow_catalog_section = f"\n{workflow_catalog.strip()}" if str(workflow_catalog or "").strip() else ""
    stable_sections = _stable_sections(
        resolved_prompt_variant,
        mode_name=mode_name,
        mode_behavior_line=mode_behavior_line,
        prompt_variant_routing=prompt_variant_routing,
        mode_definition_section=mode_definition_section,
        workflow_catalog_section=workflow_catalog_section,
        thinking_level=thinking_level,
        agent_definition=agent_definition,
        personality=personality,
        skills=skills,
    )
    dynamic_sections = _dynamic_sections(
        resolved_prompt_variant,
        system_context=system_context,
        entity_context=entity_context,
        context_compaction=context_compaction,
        checkpoint_context=checkpoint_context,
        evidence_grounding=evidence_grounding,
        repo_microagents=repo_microagents,
        repo_knowledge=repo_knowledge,
        memory=memory,
    )
    return SystemPromptParts(stable_sections=tuple(stable_sections), dynamic="\n".join(dynamic_sections))


_PERSONALITY_LANGUAGES = frozenset({"de", "en", "fr"})
_DETAIL_LEVELS = frozenset({"minimal", "standard", "detailed", "verbose"})
_STYLES = frozenset({"technical", "casual", "formal", "concise"})


def build_personality_prompt(p: Personality) -> str:
    """The Communication Preferences lines of a personality (catalog keys ``personality.*``).

    The first line pins the response language; the detail and style lines are English for
    every language (the model follows English instructions while answering in the person's language).
    """
    language = p.language if p.language in _PERSONALITY_LANGUAGES else "en"
    detail = p.detail_level if p.detail_level in _DETAIL_LEVELS else "standard"
    style = p.communication_style if p.communication_style in _STYLES else "technical"
    parts = [
        render_prompt(f"personality.language.{language}"),
        render_prompt(f"personality.detail.en.{detail}"),
        render_prompt(f"personality.style.en.{style}"),
    ]
    if p.custom_prompt:
        parts.append(p.custom_prompt)

    return "\n".join(parts)


def build_minimal_personality_prompt(personality_prompt: str) -> str:
    if not personality_prompt:
        return ""
    selected_lines = []
    for line in personality_prompt.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if clean.startswith(("Respond in the language", "Respond exclusively")):
            selected_lines.append(clean)
            continue
        if "short" in clean.lower() or "precise" in clean.lower():
            selected_lines.append(clean)
    return "\n".join(selected_lines[:2]) or personality_prompt.splitlines()[0].strip()


def build_skill_discovery_prompt() -> str:
    return render_prompt(SKILL_DISCOVERY_KEY)
