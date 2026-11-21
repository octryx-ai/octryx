"""Canonical snapshot form of an Agent Definition aggregate.

One module owns the snapshot shape so the revision lifecycle
(:mod:`app.services.agent_definition_revisions`) and the validation policy
(:mod:`app.services.agent_definition_validation`) cannot drift apart about what
a revision contains.

The snapshot holds exactly the authored content of the aggregate: the definition
header plus its ordered steps. It deliberately excludes row ids, timestamps, and
``owner_id``, because:

* excluding volatile fields is what makes the checksum *stable* — two saves of
  identical authored content hash identically, which is how content drift
  between revisions is detected;
* ``owner_id`` is attribution of the live row, not authored content, so a
  restore must not be able to move ownership.

``group_id``, ``project_id``, and ``runtime_target_id`` are kept as ``None`` or a
non-empty string. Empty strings are never written, so the validator can treat an
empty string as malformed rather than guessing between "unset" and "broken".
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..models import AgentDefinition, AgentStep
from .agent_reply_contract import snapshot_reply_contract_entry
from .agent_tool_surface_contract import snapshot_tool_surface_entry

SNAPSHOT_DEFINITION_KEY = "definition"
SNAPSHOT_STEPS_KEY = "steps"


def optional_reference(value: Any) -> str | None:
    """Normalize a nullable foreign-key value to ``None`` or a non-empty string."""
    text = str(value or "").strip()
    return text or None


def normalize_step_config(value: Any) -> dict[str, Any] | None:
    """Return *value* as a step-config mapping, or ``None`` when malformed."""
    return value if isinstance(value, dict) else None


def build_definition_snapshot(
    definition: AgentDefinition, steps: Iterable[AgentStep]
) -> dict[str, Any]:
    """Build the canonical snapshot of *definition* and its *steps*.

    *steps* must already be ordered by position; the caller loads them with an
    explicit query rather than through the lazy relationship.
    """
    return {
        SNAPSHOT_DEFINITION_KEY: {
            "name": str(definition.name or ""),
            "description": str(definition.description or ""),
            "goal": str(definition.goal or ""),
            "agent_type": str(definition.agent_type or ""),
            "thinking_level": str(definition.thinking_level or ""),
            "branch_prefix": str(definition.branch_prefix or ""),
            "system_prompt": str(definition.system_prompt or ""),
            "output_prompt": str(definition.output_prompt or ""),
            "project_id": optional_reference(definition.project_id),
            "group_id": optional_reference(definition.group_id),
            "runtime_target_id": optional_reference(definition.runtime_target_id),
            "skill_preferences": definition.skill_preferences,
            "require_self_review": bool(definition.require_self_review),
            "is_active": bool(definition.is_active),
            **snapshot_tool_surface_entry(definition.tool_surface),
            **snapshot_reply_contract_entry(definition.reply_contract_json),
            **snapshot_agent_setup_entry(definition),
        },
        SNAPSHOT_STEPS_KEY: [_snapshot_step(step) for step in steps],
    }


def snapshot_agent_setup_entry(definition: AgentDefinition) -> dict[str, Any]:
    """Ceiling, default workflow and execution mode; only non-default values, so a revision's checksum covers
    what the definition sets and never a default."""
    entry: dict[str, Any] = {}
    ceiling = str(definition.capability_ceiling or "read_only")
    if ceiling != "read_only":
        entry["capability_ceiling"] = ceiling
    if definition.default_workflow_key:
        entry["default_workflow_key"] = str(definition.default_workflow_key)
    if definition.execution_mode:
        entry["execution_mode"] = str(definition.execution_mode)
    # Same rule: only a value the definition sets.
    if definition.runtime_preference:
        entry["runtime_preference"] = str(definition.runtime_preference)
    if definition.chat_selectable:
        entry["chat_selectable"] = True
    if definition.tools_deny:
        entry["tools_deny"] = list(definition.tools_deny)
    return entry


def _snapshot_step(step: AgentStep) -> dict[str, Any]:
    return {
        "position": int(step.position or 0),
        "name": str(step.name or ""),
        "step_type": str(step.step_type or ""),
        "instructions": str(step.instructions or ""),
        "success_criteria": str(step.success_criteria or ""),
        "allowed_tools": list(step.allowed_tools),
        "step_config": step.step_config,
        "is_enabled": bool(step.is_enabled),
    }


def compute_snapshot_checksum(snapshot: dict[str, Any]) -> str:
    """Return the hex sha256 over the canonical JSON form of *snapshot*.

    Uses the repository's existing canonical-JSON checksum helper so agent
    revisions and agent export packages hash content the same way. The import is
    function-local because ``app.services.export_package`` imports the governed
    write boundary, which imports this module: at module scope the two
    would form a cycle.
    """
    from .export_package.core import checksum_for_content

    return checksum_for_content(snapshot)


def snapshot_header(snapshot: dict[str, Any]) -> dict[str, Any]:
    header = snapshot.get(SNAPSHOT_DEFINITION_KEY)
    return header if isinstance(header, dict) else {}


def snapshot_steps(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    steps = snapshot.get(SNAPSHOT_STEPS_KEY)
    if not isinstance(steps, list):
        return []
    return [step for step in steps if isinstance(step, dict)]


__all__ = [
    "SNAPSHOT_DEFINITION_KEY",
    "SNAPSHOT_STEPS_KEY",
    "build_definition_snapshot",
    "compute_snapshot_checksum",
    "normalize_step_config",
    "optional_reference",
    "snapshot_header",
    "snapshot_steps",
]
