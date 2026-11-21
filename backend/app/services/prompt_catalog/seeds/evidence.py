"""Seeds of the evidence and citation rules: the grounding contract and the Knowledge citation rule.

The only code copy of these texts; the catalog serves the published version.
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "evidence"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="evidence.grounding_contract",
        area=AREA,
        title="Evidence-Grounded Answer Contract",
        seed=(
            "## Evidence-Grounded Answer Contract\n"
            "Applies because: {applies_because}.\n"
            "Evidence status: {evidence_status}.\n"
            "Rules:\n"
            "- For project Knowledge, Jira/release/current-work, repository/deployment/architecture, and Engineering "
            "Pack/vendor-version claims, retrieve and use evidence before making definitive factual claims.\n"
            "- For live cloud/platform/operations claims, use live tool evidence before making definitive factual "
            "claims. If the user named one exact evidence tool or AWS operation, execute that bounded lookup and stop "
            "once it answers the request or returns a clear denial.\n"
            "- Treat official/vendor docs, repository files, Jira records, release artifacts, and approved Engineering "
            "Pack facts as stronger evidence than generated summaries.\n"
            "- Treat Context7 output and LLM-generated summaries as candidate material only unless they were promoted "
            "through review/source-audit workflows.\n"
            "- Separate evidence-backed facts from assumptions and recommendations when the distinction matters.\n"
            "- If evidence is missing, stale, unverified, or contradictory, say that explicitly and do not fill the "
            "gap with plausible invented details.\n"
            "- When answering, include compact provenance such as Knowledge key, Jira issue/release, repository path, "
            "or Engineering Pack item/fact/source when available. A memory from an earlier session is never "
            "provenance: present it with its present_as wording, not as a source.\n"
            "- For a bounded validation/count/status request, prefer a short Evidence checked / Result / Limits "
            "answer. Do not repeat the same lookup unless the previous evidence failed, was denied, or contradicted "
            "another source.\n"
            "- Do not repeat the same lookup to make the answer look more thorough; repeated evidence collection is a "
            "cost and quality risk when it does not add new facts.\n"
            "- If this contract applies and no relevant evidence was retrieved, answer with the known limits and the "
            "next evidence needed instead of giving a definitive answer."
        ),
        placeholders=frozenset({"applies_because", "evidence_status"}),
        risk=RISK_HIGH,
        description=(
            "Injected into the system prompt when the evidence grounding policy applies. {applies_because} joins the "
            "trigger labels with '; '; {evidence_status} is one of the two status keys."
        ),
    ),
    PromptKeySpec(
        key="evidence.status_available",
        area=AREA,
        title="Evidence status: retrieved context available",
        seed="retrieved context available: {evidence_sources}",
        placeholders=frozenset({"evidence_sources"}),
        description="Fills {evidence_status} when evidence was injected for the turn.",
    ),
    PromptKeySpec(
        key="evidence.status_missing",
        area=AREA,
        title="Evidence status: no evidence injected",
        seed="no retrieved evidence has been injected for this turn",
        description="Fills {evidence_status} when no evidence was injected for the turn.",
    ),
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
        key="evidence.trigger.default",
        area=AREA,
        title="Grounding trigger label: no trigger named",
        seed="explicit setting",
        description="Fills {applies_because} when the policy names no trigger.",
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
