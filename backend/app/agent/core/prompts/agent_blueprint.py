"""The Agent Blueprint section of a selected agent's system prompt.

Every system prompt variant that the context plan gives the blueprint carries it once, in
the stable (cacheable) part. The governed precedence boundary (``context.agent.instruction_priority``)
is its own section, placed after the Communication Preferences in the same stable part, so the
last instruction on style is the one that says the agent's task and output requirements win
over it, never over platform policy. The authored text itself is built by
``services/agent_definition_payload.build_agent_execution_prompt`` and is not changed here, so
every workflow injection sees the same payload.

The authored goal, notes, output requirements and step instructions reach the model only
through the catalog keys that carry them. A published administrator edit that drops such a
key's placeholder is reported (``prompt.agent_instruction_not_carried``), never overwritten. A
precedence body other than the current code seed (an administrator version) is reported as
``prompt.agent_instruction_priority_not_current_seed`` and rendered as published.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from app.services.agent_reply_contract_check import render_reply_contract_instruction
from app.services.agent_reply_contract_schema import REPLY_CONTRACT_PAYLOAD_KEY, ReplyContractError

from ....services.prompt_catalog import render_prompt, seed_prompt_set
from ....services.prompt_catalog.prompt_set import bound_prompt_set
from .prompt_parts import SystemPromptParts, authored_section

logger = logging.getLogger(__name__)

AGENT_BLUEPRINT_HEADING = "## Agent Blueprint"
REPLY_FORMAT_HEADING = "## Reply Format"
INSTRUCTION_PRIORITY_HEADING = "## Instruction Precedence"
INSTRUCTION_PRIORITY_KEY = "context.agent.instruction_priority"

#: Catalog key -> (placeholder that carries the authored text, agent payload field).
_INSTRUCTION_CARRIERS: tuple[tuple[str, str, str], ...] = (
    ("context.agent.execution_preamble", "goal", "goal"),
    ("context.agent.execution_notes_line", "system_prompt", "systemPrompt"),
    ("context.agent.output_line", "output_prompt", "outputPrompt"),
    ("context.agent.step", "instructions", "steps"),
)


def agent_instruction_carrier_gaps(agent_definition: Mapping[str, Any]) -> list[str]:
    """Refs (``key@version``) of active catalog bodies that drop authored text this agent has."""
    prompt_set = bound_prompt_set()
    if prompt_set is None:
        return []
    gaps: list[str] = []
    for key, placeholder, field in _INSTRUCTION_CARRIERS:
        value = agent_definition.get(field)
        authored = any(step.get("isEnabled") for step in value) if field == "steps" and value else bool(value)
        if not authored or key not in prompt_set.prompts:
            continue
        resolved = prompt_set.prompts[key]
        if f"{{{placeholder}}}" not in resolved.body:
            gaps.append(resolved.ref)
    return gaps


def _selected_prompt(agent_definition: Mapping[str, Any] | None) -> str:
    return str((agent_definition or {}).get("prompt") or "").strip()


def instruction_priority_not_current_seed() -> str | None:
    """``key@version`` when the bound precedence body is not the current code seed, else ``None``."""
    prompt_set = bound_prompt_set()
    if prompt_set is None or INSTRUCTION_PRIORITY_KEY not in prompt_set.prompts:
        return None
    resolved = prompt_set.prompts[INSTRUCTION_PRIORITY_KEY]
    seed = seed_prompt_set().prompts[INSTRUCTION_PRIORITY_KEY]
    return None if resolved.digest == seed.digest else resolved.ref


def agent_blueprint_section(agent_definition: Mapping[str, Any] | None) -> str:
    """The blueprint section, or "" when no agent instructions are selected."""
    prompt = _selected_prompt(agent_definition)
    if not prompt:
        return ""
    gaps = agent_instruction_carrier_gaps(agent_definition or {})
    if gaps:
        logger.warning(
            "prompt.agent_instruction_not_carried",
            extra={"prompt_refs": gaps, "agent_name": str((agent_definition or {}).get("name") or "")},
        )
    return f"\n{AGENT_BLUEPRINT_HEADING}\n{prompt}"


def agent_reply_format_section(agent_definition: Mapping[str, Any] | None) -> str:
    """The checked reply-format instruction of a ``json_object`` agent, or "".

    Free-text agents (and payloads without ``replyContract``) render nothing. An invalid stored
    contract renders nothing either: its turn is held as ``needs_configuration`` before any model call.
    The authored payload prompt and goals are never changed.
    """
    if not isinstance(agent_definition, Mapping) or REPLY_CONTRACT_PAYLOAD_KEY not in agent_definition:
        return ""
    try:
        instruction = render_reply_contract_instruction(agent_definition[REPLY_CONTRACT_PAYLOAD_KEY])
    except ReplyContractError:
        return ""
    return f"\n{REPLY_FORMAT_HEADING}\n{instruction}" if instruction else ""


def ensure_reply_format_section(parts: SystemPromptParts,
                                agent_definition: Mapping[str, Any] | None) -> SystemPromptParts:
    """The system prompt parts with the reply-format section whenever the reply check is enforced.

    The check reads the selected payload on every turn, but the plan may leave the blueprint out
    (``context_plan.include_agent_blueprint``) and the ``bounded_evidence`` variant carries no agent
    sections at all. A format is never checked that the model was not told, so the
    section is appended to the stable part (authored material) when it is missing.
    """
    section = agent_reply_format_section(agent_definition)
    if not section or REPLY_FORMAT_HEADING in parts.stable:
        return parts
    # The sections join with a newline; the section's own leading newline is that separator.
    return replace(parts, stable_sections=(*parts.stable_sections, authored_section(section.removeprefix("\n"))))


def agent_instruction_priority_section(agent_definition: Mapping[str, Any] | None) -> str:
    """The governed precedence section for a selected agent, or "" without agent instructions."""
    if not _selected_prompt(agent_definition):
        return ""
    not_current = instruction_priority_not_current_seed()
    if not_current:
        # Published administrator governance wins: report, never overwrite or re-inject the seed.
        logger.warning("prompt.agent_instruction_priority_not_current_seed", extra={"prompt_ref": not_current})
    return f"\n{INSTRUCTION_PRIORITY_HEADING}\n{render_prompt(INSTRUCTION_PRIORITY_KEY)}"


__all__ = [
    "AGENT_BLUEPRINT_HEADING",
    "INSTRUCTION_PRIORITY_HEADING",
    "INSTRUCTION_PRIORITY_KEY",
    "REPLY_FORMAT_HEADING",
    "agent_blueprint_section",
    "agent_instruction_carrier_gaps",
    "agent_instruction_priority_section",
    "agent_reply_format_section",
    "ensure_reply_format_section",
    "instruction_priority_not_current_seed",
]
