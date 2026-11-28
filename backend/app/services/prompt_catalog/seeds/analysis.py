"""Seeds of the request-analysis and evidence-planning prompts: the execution contract, the bounded AWS read, the AWS
topology detail selection and the person-research follow-up reminders."""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "analysis"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="analysis.execution_contract",
        area=AREA,
        title="Request analysis execution contract",
        seed=(
            "Execution contract:\n"
            "0. Language contract:\n"
            "   - Source language: {source_language}\n"
            "   - Canonical working language: {canonical_language}\n"
            "   - Final response language: {output_language}\n"
            "   - Use English for intent analysis, planning, and workflow selection.\n"
            "   - Write the final answer in the configured final response language unless the user explicitly requests "
            "another language.\n"
            "1. Analyze the request and required coverage before choosing tools.\n"
            "2. Required domains: {domains_text}.\n"
            "3. Limit policy: {limit_policy}.\n"
            "4. Only finalize after required domain coverage is satisfied or you explicitly state what is still "
            "missing."
        ),
        placeholders=frozenset(
            {
                "canonical_language",
                "domains_text",
                "limit_policy",
                "output_language",
                "source_language",
            }
        ),
        risk=RISK_HIGH,
        description=(
            "Injected when the request analysis requires coverage first; languages, domains and limit policy are "
            "filled by code."
        ),
    ),
    PromptKeySpec(
        key="analysis.aws_topology.detail_selection",
        area=AREA,
        title="AWS topology detail selection",
        seed=(
            "The AWS topology overview artifact is already created, but it does not satisfy this workflow yet because "
            "this snapshot is too large for a single readable canvas.\n"
            "Decide which focused diagram artifacts are still useful from the snapshot-derived candidates below. Do "
            "not blindly create every candidate.\n"
            "Your next assistant response must call `create_diagram`; prose-only completion messages will be rejected. "
            "Create 1-3 separate focused draw.io diagrams now, one tool call per chosen artifact. Prioritize the areas "
            "with dense relationships, security relevance, or architectural value. Use only nodes and relationships "
            "present in the AWS topology snapshot evidence.\n"
            "Snapshot size: {node_count} candidate nodes, {edge_count} candidate edges.\n"
            "Detail candidates:"
        ),
        placeholders=frozenset({"edge_count", "node_count"}),
        risk=RISK_HIGH,
        description=(
            "System reminder when the AWS topology overview is too large; one detail-candidate line per candidate "
            "follows on its own line."
        ),
    ),
    PromptKeySpec(
        key="analysis.aws_topology.detail_candidate",
        area=AREA,
        title="AWS topology detail candidate line",
        seed=(
            "- {candidate_id}: {title} ({estimated_nodes} nodes, {estimated_edges} edges). Reason: {reason} Node "
            "types: {node_types}. Edge types: {edge_types}."
        ),
        placeholders=frozenset(
            {
                "candidate_id",
                "edge_types",
                "estimated_edges",
                "estimated_nodes",
                "node_types",
                "reason",
                "title",
            }
        ),
        description="One snapshot-derived candidate of the detail selection reminder.",
    ),
)
