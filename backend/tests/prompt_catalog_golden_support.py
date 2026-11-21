"""Fixed inputs for the prompt catalog golden test (``test_prompt_catalog_golden.py``).

Each scenario renders a catalog-backed prompt surface with fixed inputs. The golden test pins the SHA-256 of every
output; rendering the same scenario from the seeded catalog must give the same bytes. ``golden_outputs`` is the
single scenario builder used both to pin and to check.
"""

from __future__ import annotations

from hashlib import sha256
from itertools import product
from typing import Any

from app.agent.core.context.evidence_grounding import EvidenceGroundingPolicy, render_evidence_grounding_prompt
from app.agent.core.prompts.prompt_builder import build_skill_discovery_prompt, build_system_prompt_parts

VARIANTS = ("bounded_evidence", "minimal", "summary", "admin", "full")
CAPABILITIES = ("diagnosis", "change", "plan", "admin")
THINKING = (None, "off", "light", "deep")
MODE_INSTRUCTIONS = ("", "Custom mode text.")


class GoldenMode:
    def __init__(self, capability_type: str, prompt_instructions: str) -> None:
        self.key = f"{capability_type}-mode"
        self.name = capability_type.title()
        self.capability_type = capability_type
        self.prompt_instructions = prompt_instructions


SECTIONS: dict[str, Any] = {
    "personality": "Respond exclusively in English.",
    "memory": "Remembered fact.",
    "skills": "Skill hint.",
    "entity_context": "Entity A.",
    "context_compaction": "Compacted.",
    "checkpoint_context": "Checkpoint.",
    "evidence_grounding": "## Evidence\nRule.",
    "repo_microagents": "## Repo Microagents\nm",
    "repo_knowledge": "## Repo Knowledge\nk",
    "system_context": {
        "os_name": "Linux",
        "os_release": "6",
        "shell": "bash",
        "workspace_root": "/w",
        "available_binaries": {"git": "/usr/bin/git"},
        "command_hints": {"recent_date": "date", "notes": "n"},
    },
    "agent_definition": {"prompt": "Blueprint text."},
    "workflow_catalog": "## Workflow Catalog\n- w",
}


def _system_scenarios() -> dict[str, str]:
    outputs: dict[str, str] = {}
    for variant, capability, thinking, instructions in product(VARIANTS, CAPABILITIES, THINKING, MODE_INSTRUCTIONS):
        parts = build_system_prompt_parts(
            agent_type=capability,
            agent_mode=GoldenMode(capability, instructions),
            thinking_level=thinking,
            prompt_variant=variant,
            **SECTIONS,
        )
        name = f"system:{variant}:{capability}:{thinking}:{bool(instructions)}"
        outputs[name] = parts.stable + "\x00" + parts.dynamic
    return outputs


def _evidence_scenarios() -> dict[str, str]:
    # Pinned for the renderer that reads triggers, not prompt domains.
    with_evidence = EvidenceGroundingPolicy(
        applies=True,
        triggers=("workflow_requires_sources", "high_risk_agent_type", "custom_trigger"),
        evidence_available=True,
        evidence_sources=("engineering_knowledge", "repository_context"),
        reason="test",
    )
    without_evidence = EvidenceGroundingPolicy(
        applies=True, triggers=(), evidence_available=False, evidence_sources=(), reason="test"
    )
    return {
        "evidence:with": render_evidence_grounding_prompt(with_evidence),
        "evidence:without": render_evidence_grounding_prompt(without_evidence),
    }


def golden_outputs() -> dict[str, str]:
    return {
        **_system_scenarios(),
        **_evidence_scenarios(),
        "skills:discovery": build_skill_discovery_prompt(),
    }


def golden_digests() -> dict[str, str]:
    return {name: sha256(text.encode("utf-8")).hexdigest() for name, text in golden_outputs().items()}
