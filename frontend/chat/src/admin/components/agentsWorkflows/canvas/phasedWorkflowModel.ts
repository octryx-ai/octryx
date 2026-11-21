// A workflow that runs in phases, as its editor shows it. Pure: the payload of
// /api/v1/phased-workflows/{flow_id}, the labels of the closed node kinds and the addresses the editor uses.

export type PhasedNode = {
  id: string;
  kind: string;
  title: string;
  capability_class?: string | null;
  steps?: number;
  checks?: number;
  path_rules?: string[];
  outcome?: string;
  subject?: string;
  question?: string;
  tool?: string;
  workflow_key?: string;
  conditions?: string[];
  agent?: string;
  action?: string;
  output?: string;
  options?: string[];
  // The node's raw settings, shown under "Details" in the designer's side panel.
  config?: Record<string, unknown>;
};
export type PhasedEdge = {
  id: string;
  source: string;
  target: string;
  kind: string;
  when: string | null;
  max_iterations: number | null;
  title: string;
};
// A validation problem; the box or arrow it concerns when it names one (designer D2b1).
export type PhasedIssue = { code: string; message: string; node_id?: string; edge_id?: string };
export type PhasedView = {
  flow_id: string;
  key: string;
  title: string;
  status: string;
  version_id: string;
  version: number;
  version_status: string;
  published_version: number | null;
  editable: boolean;
  nodes: PhasedNode[];
  edges: PhasedEdge[];
  validation_report: {
    valid: boolean;
    errors: PhasedIssue[];
    warnings: PhasedIssue[];
  };
  // Where the designer draws each box (UI metadata of the version; missing boxes are auto-laid out), the boxes
  // grouped by hand and the direction it is drawn in.
  layout?: {
    positions?: Record<string, { x: number; y: number }>;
    groups?: { id: string; label: string; members: string[] }[];
    direction?: string;
  };
  // The stored definition the designer edits (D2b1), and whether it is built from fragments (then only moved).
  definition?: Record<string, unknown>;
  composite?: boolean;
  // Four eyes (D2b2): "awaiting_approval" once the author asked for publishing.
  review_state?: string | null;
  /** Four eyes for this viewer, decided on the server: false for the author when a second admin must publish. */
  can_publish?: boolean;
  publish_reason?: string;
  project_id?: string | null;
};

export const phasedDefinitionPath = (flowId: string) => `${phasedViewPath(flowId)}/definition`;
export const PHASED_CREATE_PATH = "/api/v1/phased-workflows";
export const designerCatalogPath = (projectId?: string | null) =>
  `/api/v1/phased-workflows/catalog${projectId ? `?project_id=${encodeURIComponent(projectId)}` : ""}`;
export const flowReviewPath = (versionId: string) =>
  `/api/v1/flows/versions/${encodeURIComponent(versionId)}/request-review`;

// A refused publish in plain words: the author of a version does not publish it alone (four eyes, D2b2).
export function publishProblem(error: unknown, fallback: string): string {
  const code = (error as { code?: unknown } | null)?.code;
  if (code === "workflow_four_eyes") {
    return "A second admin publishes this version. Use “Request publishing”; another admin then publishes it.";
  }
  return error instanceof Error ? error.message : fallback;
}

// The version's state for the designer's header: "draft", "in review" (D2b2) or "published".
export function designerStatus(
  view: Pick<PhasedView, "version_status" | "review_state">,
): "draft" | "in review" | "published" | "archived" {
  if (view.version_status === "published") return "published";
  if (view.version_status === "in_review" || (view.version_status === "draft" && view.review_state === "awaiting_approval")) {
    return "in review";
  }
  return view.version_status === "archived" ? "archived" : "draft";
}

// The designer edits a draft of an active workflow that is not built from fragments; anything else is shown read
// only ("Edit as draft" makes a draft of a published version).
export function designerEditable(view: Pick<PhasedView, "editable" | "version_status" | "composite">): boolean {
  return view.editable && view.version_status === "draft" && !view.composite;
}

export const NODE_KIND_LABELS: Record<string, string> = {
  start: "Start",
  phase: "Phase",
  gate: "Gate",
  decision: "Decision",
  outcome: "Outcome",
  platform_action: "Platform action",
  user_conversation: "Ask the user",
  user_confirmation: "User confirmation",
  watch: "Wait for external state",
  approval: "Approval (four-eyes)",
  sub_workflow: "Sub-workflow",
  review: "Independent review",
  pause: "Pause for the requester",
};

export const phasedViewPath = (flowId: string) =>
  `/api/v1/phased-workflows/${encodeURIComponent(flowId)}`;
export const phaseGraphPath = (flowId: string, nodeId: string) =>
  `${phasedViewPath(flowId)}/phases/${encodeURIComponent(nodeId)}/graph`;
export const phasedLayoutPath = (flowId: string) => `${phasedViewPath(flowId)}/layout`;
export const flowPublishPath = (versionId: string) =>
  `/api/v1/flows/versions/${encodeURIComponent(versionId)}/publish`;

// One line per node: what it does, in the words of its kind.
export function nodeDetail(node: PhasedNode): string {
  if (node.kind === "phase") {
    const rules = node.path_rules?.length
      ? ` · writes only ${node.path_rules.join(", ")}`
      : "";
    return `${node.capability_class ?? "class not set"} · ${node.steps ?? 0} steps · ${node.checks ?? 0} checks${rules}`;
  }
  if (node.kind === "gate")
    return `${node.checks ?? 0} checks over the last phase's evidence`;
  if (node.kind === "outcome") return node.outcome ?? "";
  if (node.kind === "user_confirmation")
    return node.subject?.replace(/_/g, " ") ?? "";
  if (node.kind === "user_conversation") return node.question ?? "";
  if (node.kind === "platform_action") return node.tool ?? "";
  if (node.kind === "sub_workflow") return node.workflow_key ?? "";
  if (node.kind === "watch") return (node.conditions ?? []).join(", ");
  if (node.kind === "pause")
    return "a failed step: retry, change or abort; not recoverable → its exit";
  return "";
}

// "Implement ↔ Gate: green · at most 3" for a loop edge.
export function loopLine(edge: PhasedEdge, nodes: PhasedNode[]): string {
  const title = (id: string) =>
    nodes.find((node) => node.id === id)?.title ?? id;
  const name = edge.title || `${title(edge.target)} ↔ ${title(edge.source)}`;
  const route = edge.when ? ` (on ${edge.when})` : "";
  return `${name}: back to ${title(edge.target)}${route} · at most ${edge.max_iterations ?? "?"}`;
}

export function exitsOf(
  node: PhasedNode,
  edges: PhasedEdge[],
  nodes: PhasedNode[],
): string[] {
  const title = (id: string) =>
    nodes.find((item) => item.id === id)?.title ?? id;
  return edges
    .filter((edge) => edge.source === node.id && edge.kind !== "loop")
    .map((edge) =>
      edge.when
        ? `${edge.when} → ${title(edge.target)}`
        : `→ ${title(edge.target)}`,
    );
}

export function publishable(view: PhasedView): boolean {
  return (
    view.editable &&
    view.version_status === "draft" &&
    view.validation_report.valid
  );
}

// The version state, said once ("PUBLISHED V8 · PUBLISHED V8"): "Published v8", "Draft v9 · published v8",
// "Draft v1 · not published yet".
export function phasedStatusLabel(
  view: Pick<PhasedView, "version" | "version_status" | "published_version">,
): string {
  const state = view.version_status ? view.version_status.charAt(0).toUpperCase() + view.version_status.slice(1) : "Version";
  const own = `${state} v${view.version}`;
  if (view.version_status === "published" && (view.published_version == null || view.published_version === view.version)) {
    return own;
  }
  if (view.published_version == null) return view.version_status === "draft" ? `${own} · not published yet` : own;
  if (view.published_version === view.version) return own;
  return `${own} · published v${view.published_version}`;
}

// Why Publish is disabled, in one short sentence; "" when it can be used.
export function publishBlockReason(
  view: Pick<PhasedView, "editable" | "version" | "version_status" | "validation_report">,
  state: { unsavedLayout?: boolean; busy?: boolean } = {},
): string {
  if (!view.editable) return "Archived workflows cannot be published.";
  if (state.unsavedLayout) return "Save or undo the moved boxes first.";
  if (view.version_status !== "draft") return `No draft changes: v${view.version} is already ${view.version_status}.`;
  const errors = view.validation_report.errors.length;
  if (!view.validation_report.valid) {
    return errors === 1 ? "Fix the problem listed above first." : `Fix the ${errors || ""} problems listed above first.`.replace("  ", " ");
  }
  if (state.busy) return "Working…";
  return "";
}
