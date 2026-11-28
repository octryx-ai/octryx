"""Seeds of the evidence and citation rules: the grounding contract and the Knowledge citation rule."""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "evidence"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="evidence.trigger.workflow_requires_sources",
        area=AREA,
        title="Grounding trigger label: workflow_requires_sources",
        seed="the selected workflow requires sources",
        description="One reason in {applies_because} of the grounding contract.",
    ),
    PromptKeySpec(
        key="evidence.trigger.workflow_requires_live_evidence",
        area=AREA,
        title="Grounding trigger label: workflow_requires_live_evidence",
        seed="the selected workflow requires live evidence",
        description="One reason in {applies_because} of the grounding contract.",
    ),
    PromptKeySpec(
        key="evidence.trigger.high_risk_agent_type",
        area=AREA,
        title="Grounding trigger label: high_risk_agent_type",
        seed="the agent type is configured as high-risk",
        description="One reason in {applies_because} of the grounding contract.",
    ),
    PromptKeySpec(
        key="evidence.trigger.workspace_setting_required",
        area=AREA,
        title="Grounding trigger label: workspace_setting_required",
        seed="the Workspace requires evidence grounding",
        description="One reason in {applies_because} of the grounding contract.",
    ),
    PromptKeySpec(
        key="evidence.trigger.workspace_setting_needs_configuration",
        area=AREA,
        title="Grounding trigger label: workspace_setting_needs_configuration",
        seed="the Workspace grounding setting needs configuration",
        description="One reason in {applies_because} of the grounding contract.",
    ),
    PromptKeySpec(
        key="evidence.citation_rule",
        area=AREA,
        title="Citation rule of the Knowledge tools",
        seed=(
            "State only what a returned passage or fact says: add no comparison with earlier versions, no background "
            "knowledge and no number that no cited source states."
        ),
        risk=RISK_HIGH,
        description="Last sentence of the knowledge_search and knowledge_changes tool descriptions (A1 depends on it).",
    ),
)
