"""Seeds of the tool-result prompts: tool working-set summaries and compact tool-result guidance.

Registered through ``seeds/tool_guard.py`` (one area). The only code copy of these texts.
"""

from __future__ import annotations

from ..contract import RISK_HIGH, PromptKeySpec

AREA = "tool_guard"

SPECS: tuple[PromptKeySpec, ...] = (
    PromptKeySpec(
        key="tool_guard.working_set.collapsed_header",
        area=AREA,
        title="Earlier tool progress: header",
        seed="## Earlier Tool Progress Summary",
    ),
    PromptKeySpec(
        key="tool_guard.working_set.collapsed_sequence",
        area=AREA,
        title="Earlier tool progress: sequence line",
        seed="- Collapsed tool sequence: {sequence}",
        placeholders=frozenset({"sequence"}),
    ),
    PromptKeySpec(
        key="tool_guard.working_set.collapsed_note",
        area=AREA,
        title="Earlier tool progress: compaction note",
        seed="- Older tool interactions were compacted to control token growth.",
    ),
    PromptKeySpec(
        key="tool_guard.working_set.collapsed_reload",
        area=AREA,
        title="Earlier tool progress: reload hint",
        seed="- Reload detail only with `load_tool_artifact` if one of these older artifacts becomes relevant again.",
    ),
    PromptKeySpec(
        key="tool_guard.working_set.turn_header",
        area=AREA,
        title="Turn working summary: header",
        seed="## Turn Working Summary",
    ),
    PromptKeySpec(
        key="tool_guard.working_set.turn_sequence",
        area=AREA,
        title="Turn working summary: sequence line",
        seed="- Recent tool sequence: {sequence}",
        placeholders=frozenset({"sequence"}),
    ),
    PromptKeySpec(
        key="tool_guard.working_set.turn_artifacts",
        area=AREA,
        title="Turn working summary: artifacts header",
        seed="- Important processed artifacts:",
    ),
    PromptKeySpec(
        key="tool_guard.working_set.turn_reload",
        area=AREA,
        title="Turn working summary: reload hint",
        seed=(
            "- If older detail is missing, call `load_tool_artifact` for the specific artifact_id instead of broad "
            "re-fetching."
        ),
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.inventory_note",
        area=AREA,
        title="AWS topology result: inventory note",
        seed=(
            "Full topology nodes and edges are stored in the tool artifact; this compact view is optimized for service "
            "inventory synthesis."
        ),
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.diagram_note",
        area=AREA,
        title="AWS topology result: diagram note",
        seed=(
            "Full topology nodes and edges are stored in the tool artifact; diagram_brief is a bounded real topology "
            "view for draw.io generation."
        ),
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.brief.selected_edges",
        area=AREA,
        title="AWS diagram brief: selected edges only",
        seed="Use only selected_edges for relationships; do not draw invented service-to-service chains.",
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.brief.full_overview",
        area=AREA,
        title="AWS diagram brief: full overview",
        seed=(
            "Full overview mode requested: draw all selected_nodes and selected_edges across visible services; use "
            "append_diagram if needed."
        ),
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.brief.node_refs",
        area=AREA,
        title="AWS diagram brief: node refs",
        seed="Use selected_nodes.ref as stable mxCell ids when refs are present.",
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.brief.compact",
        area=AREA,
        title="AWS diagram brief: compact",
        seed="Compact mode requested: keep the diagram intentionally small and readable.",
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.brief.aggregate",
        area=AREA,
        title="AWS diagram brief: aggregate",
        seed="Aggregate repeated nodes when the selected view is still too busy.",
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.brief.catalog_only",
        area=AREA,
        title="AWS diagram brief: catalog-only nodes",
        seed="Catalog-only Bedrock model nodes are omitted by default; draw Bedrock only if the user asked for it.",
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.guidance.diagram_relationships",
        area=AREA,
        title="AWS guidance: diagram relationships",
        seed="Use diagram_brief.selected_nodes and selected_edges as the only relationship evidence.",
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.guidance.no_invented_chains",
        area=AREA,
        title="AWS guidance: no invented chains",
        seed="Do not draw invented service chains or catalog-only Bedrock model visibility as workload topology.",
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.guidance.full_overview",
        area=AREA,
        title="AWS guidance: full overview",
        seed="Full overview requested: draw the broad selected topology across visible services.",
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.guidance.compact",
        area=AREA,
        title="AWS guidance: compact",
        seed="Keep the diagram compact; aggregate omitted resources when needed.",
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.guidance.inventory_only",
        area=AREA,
        title="AWS guidance: inventory only",
        seed=(
            "Answer as visible AWS resource inventory unless Cost Explorer, CloudTrail, or metrics evidence was "
            "retrieved."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.guidance.no_usage_claims",
        area=AREA,
        title="AWS guidance: no usage claims",
        seed=(
            "Do not describe STS identity evidence or Bedrock model catalog visibility as workload usage by "
            "themselves."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.guidance.partial_services",
        area=AREA,
        title="AWS guidance: partial services",
        seed="If a service is listed in services_partial, report it as detected with partial warnings, not as absent.",
    ),
    PromptKeySpec(
        key="tool_guard.compression.aws.guidance.concise",
        area=AREA,
        title="AWS guidance: concise",
        seed="Keep the final answer concise and evidence-grounded.",
    ),
    PromptKeySpec(
        key="tool_guard.compression.code_structure.note",
        area=AREA,
        title="Code-structure result: note",
        seed=(
            "Full snapshot payload is stored in the tool artifact; diagram_brief is the bounded literal code-structure "
            "evidence for deterministic diagram rendering."
        ),
    ),
    PromptKeySpec(
        key="tool_guard.compression.kubernetes.guidance",
        area=AREA,
        title="Kubernetes result: guidance",
        seed=(
            "Use topology_summary for inventory counts and diagram_brief.selected_edges for relationships. Do not "
            "invent Kubernetes relationships that are not present in selected_edges."
        ),
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.compression.kubernetes.note",
        area=AREA,
        title="Kubernetes result: note",
        seed=(
            "Full Kubernetes topology nodes and edges are stored in the tool artifact; this compact view keeps the "
            "bounded topology summary and diagram evidence for model reasoning."
        ),
    ),
    PromptKeySpec(
        key="tool_guard.workflow_result.no_invention",
        area=AREA,
        title="Workflow capability result: no invention",
        seed="Do not invent source profiles, channels, repositories, tickets, dates, roles, or counts.",
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.workflow_result.missing_source",
        area=AREA,
        title="Workflow capability result: missing source",
        seed="If a source is missing or has zero matches, say that the workflow did not provide that evidence.",
        risk=RISK_HIGH,
    ),
    PromptKeySpec(
        key="tool_guard.workflow_result.quality_priority",
        area=AREA,
        title="Workflow capability result: quality priority",
        seed="Prefer incomplete-but-evidenced answers over complete-looking unsupported claims.",
    ),
)
