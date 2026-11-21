// The designer's problem list (D2b1): what the side panel finds while the person draws (nodeConfigIssues,
// edgeIssues, and the shape of the whole workflow) merged with the backend's validation report of the saved draft.
// Each problem names its box or arrow, so a click selects it. Pure.
import { edgeIssues } from "./inspector/patch";
import { kindName } from "./inspector/labels";
import { nodeConfigIssues } from "./inspector/nodeIssues";
import type { DesignModel } from "./modelCore";
import type { DefNode, DesignerCatalog } from "./types";

export type DesignIssue = { key: string; message: string; nodeId?: string; edgeId?: string; field?: string };
export type ReportIssue = { code: string; message: string; node_id?: string; edge_id?: string };

// The backend's codes the panel already checks live with the same rules: its message for a box or arrow that still
// exists would only repeat (in other words, and as of the last save) what the list says now.
const LIVE_CODES = new Set([
  "phase_without_contract", "phase_capability_class", "phase_without_checks", "invalid_path_rules", "path_rules_with_shell",
  "gate_without_checks", "gate_check_type", "gate_phase", "unknown_check_type", "decision_source", "decision_options",
  "outcome_value", "action_without_tool", "action_arguments", "unknown_platform_action", "confirmation_subject",
  "conversation_question", "watch_conditions", "sub_workflow_key", "decider_invalid", "phase_without_agent",
  "phase_agent_unknown", "phase_agent_ceiling", "unbounded_loop", "limit_on_next_edge", "unexpected_route", "unknown_route",
  "duplicate_route", "ambiguous_exit", "outcome_exit", "dead_end", "start_count", "no_outcome", "on_open_high",
]);

export const boxName = (node: DefNode | undefined) => (node ? `“${node.label || kindName(node.type)}”` : "A removed box");

/** What is wrong now, while the person draws. */
export function liveIssues(model: DesignModel, catalog: DesignerCatalog): DesignIssue[] {
  const issues: DesignIssue[] = [];
  const byId = new Map(model.nodes.map((node) => [node.id, node]));
  const starts = model.nodes.filter((node) => node.type === "start");
  if (starts.length !== 1) issues.push({ key: "start_count", message: "A workflow has exactly one Start box." });
  if (!model.nodes.some((node) => node.type === "outcome")) issues.push({ key: "no_outcome", message: "Add an End box: every workflow ends somewhere." });
  for (const node of model.nodes) {
    for (const issue of nodeConfigIssues(node, model.nodes, catalog)) {
      issues.push({ key: `n:${node.id}:${issue.path}:${issue.message}`, message: `${boxName(node)}: ${issue.message}`, nodeId: node.id, field: issue.path });
    }
    if (node.type !== "outcome" && !model.edges.some((edge) => edge.source === node.id && edge.kind === "next")) {
      issues.push({ key: `n:${node.id}:dead_end`, message: `${boxName(node)} needs an arrow to the next box.`, nodeId: node.id });
    }
  }
  for (const edge of model.edges) {
    const arrow = `The arrow from ${boxName(byId.get(edge.source))} to ${boxName(byId.get(edge.target))}`;
    for (const issue of edgeIssues(edge, model.edges, model.nodes, catalog)) {
      issues.push({ key: `e:${edge.id}:${issue.path}:${issue.message}`, message: `${arrow}: ${issue.message}`, edgeId: edge.id, field: issue.path });
    }
  }
  return issues;
}

/**
 * The live problems and the backend's report of the saved draft: a report problem the panel checks live is left out
 * while its box or arrow exists (and one about a box that is gone); every other one stays, named by its box.
 */
export function mergedIssues(live: DesignIssue[], report: ReportIssue[], model: DesignModel): DesignIssue[] {
  const nodes = new Set(model.nodes.map((node) => node.id));
  const edges = new Set(model.edges.map((edge) => edge.id));
  const merged = [...live];
  const said = new Set(live.map((issue) => issue.message));
  for (const [index, item] of report.entries()) {
    const nodeId = item.node_id && nodes.has(item.node_id) ? item.node_id : undefined;
    const edgeId = item.edge_id && edges.has(item.edge_id) ? item.edge_id : undefined;
    if ((item.node_id && !nodeId && !item.edge_id) || (item.edge_id && !edgeId)) continue;  // about something removed
    if (LIVE_CODES.has(item.code)) continue;
    if (said.has(item.message)) continue;
    said.add(item.message);
    merged.push({ key: `r:${index}:${item.code}`, message: item.message, nodeId, edgeId });
  }
  return merged;
}
