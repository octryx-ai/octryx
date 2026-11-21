"""Seeds of the workflow capability section and the workflow catalog rules.

The ``## Workflow catalog`` heading stays a code constant (the loop detects the section by it).
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "workflow"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="workflow.catalog.rules",
        area=AREA,
        title="Workflow catalog: selection rules",
        seed=(
            "Governed workflows. When the request clearly matches one entry and no workflow is active yet, call "
            "`select_workflow` with its workflow_key BEFORE other tools; its contract then drives the tool plan. "
            "When no entry matches, answer directly. An explicit user selection always takes precedence."
        ),
        risk=RISK_HIGH,
        description="Follows the fixed '## Workflow catalog' heading the loop detects; the catalog entries follow.",
    ),
)
