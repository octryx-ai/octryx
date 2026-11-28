"""Seeds of the tool-result prompts: tool working-set summaries and compact tool-result guidance."""

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
)
