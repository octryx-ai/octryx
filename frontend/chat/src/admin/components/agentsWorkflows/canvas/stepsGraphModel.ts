// One phase of a workflow that runs in phases, as its steps and checks on the Canvas. The server owns the graph
// (`/api/v1/phased-workflows/{flow_id}/phases/{node_id}/graph`): stored nodes carry the raw `source_steps` /
// `checks` entry, derived nodes (start, approvals, result) explain the run. Edits here only change the stored nodes'
// raw entries and their order; the server re-derives everything else (preview) and saves a draft version of the
// workflow.
import { checkTypeLabel } from "./checkTypeLabels";
import type { FlowDefinitionEdge, FlowDefinitionNode } from "../../flowBuilder/flowBuilderTypes";
import type { BadgeKind } from "../awBadges";

type Json = Record<string, unknown>;

export type StepsNodeKind = "start" | "approval" | "step" | "check" | "result";

export type StepsGraphNode = {
  id: string;
  kind: StepsNodeKind;
  derived?: boolean;
  step?: Json;
  check?: Json;
  tool?: string;
  label?: string;
  required?: boolean;
  mode?: string;
  mode_explicit?: boolean;
  allowed?: boolean;
  type?: string;
  description?: string;
  blocking?: boolean;
  reason?: string;
  capability_class?: string;
};

export type StepsGraph = { capabilityClass: string; nodes: StepsGraphNode[] };

export type ValidationIssue = { code: string; message: string };

export type ValidationReport = {
  valid: boolean;
  errors: ValidationIssue[];
  warnings: ValidationIssue[];
};

export type StepsGraphView = {
  key: string;
  title: string;
  status: string;
  versionId: string;
  version: number;
  versionStatus: string;
  editable: boolean;
  readOnlyReason: string;
  checkTypes: string[];
  advisoryCheckTypes: string[];
  stepModes: string[];
  report: ValidationReport;
  graph: StepsGraph;
};

const record = (value: unknown): Json => (value && typeof value === "object" && !Array.isArray(value) ? (value as Json) : {});
const list = (value: unknown): unknown[] => (Array.isArray(value) ? value : []);
const text = (value: unknown): string => (typeof value === "string" ? value : value == null ? "" : String(value));
const KINDS: StepsNodeKind[] = ["start", "approval", "step", "check", "result"];

const issues = (value: unknown): ValidationIssue[] =>
  list(value).map((item) => ({ code: text(record(item).code), message: text(record(item).message) }));

export function readValidationReport(raw: unknown): ValidationReport {
  const report = record(raw);
  return {
    valid: report.valid !== false,
    errors: issues(report.errors),
    warnings: issues(report.warnings),
  };
}

export function readStepsGraph(raw: unknown): StepsGraph {
  const graph = record(raw);
  return {
    capabilityClass: text(graph.capability_class),
    nodes: list(graph.nodes).flatMap((item) => {
      const node = record(item);
      const kind = text(node.kind) as StepsNodeKind;
      return KINDS.includes(kind) ? [{ ...node, id: text(node.id), kind } as StepsGraphNode] : [];
    }),
  };
}

export function readStepsGraphView(raw: unknown): StepsGraphView {
  const body = record(raw);
  return {
    key: text(body.key),
    title: text(body.title),
    status: text(body.status),
    versionId: text(body.version_id),
    version: Number(body.version) || 0,
    versionStatus: text(body.version_status),
    editable: body.editable === true,
    readOnlyReason: text(body.read_only_reason),
    checkTypes: list(body.check_types).map(text),
    advisoryCheckTypes: list(body.advisory_check_types).map(text),
    stepModes: list(body.step_modes).map(text),
    report: readValidationReport(body.validation_report),
    graph: readStepsGraph(body.graph),
  };
}

// The shown version's state: "Published v2", "Draft v3".
export function stepsStatusLabel(view: Pick<StepsGraphView, "status" | "version" | "versionStatus">): string {
  if (view.status === "published") return `Published v${view.version}`;
  return `${view.versionStatus === "draft" ? "Draft" : view.status} v${view.version}`;
}

// --- Edits: only stored nodes change; the posted graph keeps the derived ones (the server ignores them). ---

let newNodeSeq = 0;
const newId = (kind: string) => `new-${kind}-${Date.now().toString(36)}-${(newNodeSeq += 1)}`;
const isStored = (node: StepsGraphNode) => node.kind === "step" || node.kind === "check";

function insertAt(nodes: StepsGraphNode[], index: number, node: StepsGraphNode): StepsGraphNode[] {
  return [...nodes.slice(0, index), node, ...nodes.slice(index)];
}

// A new step or check before it joins the workflow: the editor's "+ Step" / "+ Check" side panel edits it as a local
// draft, and only "Add step" / "Add check" inserts it, so the workflow's draft does not change before anything is chosen.
export function newStep(tool: string): StepsGraphNode {
  return { id: newId("step"), kind: "step", step: { tool }, tool, required: true };
}

export function newCheck(type: string): StepsGraphNode {
  return { id: newId("check"), kind: "check", check: { type, blocking: false, description: "" }, type };
}

// A new step goes after the last step (before the checks), a new check before the result.
export function insertNode(nodes: StepsGraphNode[], node: StepsGraphNode): StepsGraphNode[] {
  if (node.kind === "step") {
    const firstAfterSteps = nodes.findIndex((item) => item.kind === "check" || item.kind === "result");
    return insertAt(nodes, firstAfterSteps < 0 ? nodes.length : firstAfterSteps, node);
  }
  const result = nodes.findIndex((item) => item.kind === "result");
  return insertAt(nodes, result < 0 ? nodes.length : result, node);
}

export function addStep(nodes: StepsGraphNode[], tool: string): { nodes: StepsGraphNode[]; id: string } {
  const node = newStep(tool);
  return { nodes: insertNode(nodes, node), id: node.id };
}

export function addCheck(nodes: StepsGraphNode[], type: string): { nodes: StepsGraphNode[]; id: string } {
  const node = newCheck(type);
  return { nodes: insertNode(nodes, node), id: node.id };
}

// The same patch as updateStep / updateCheck, for the one node a side panel holds before it is added.
export function patchNode(node: StepsGraphNode, patch: Json): StepsGraphNode {
  if (node.kind === "step") return { ...node, step: patched(node.step, patch) };
  if (node.kind === "check") return { ...node, check: patched(node.check, patch) };
  return node;
}

export function removeNode(nodes: StepsGraphNode[], id: string): StepsGraphNode[] {
  return nodes.filter((node) => !(node.id === id && isStored(node)));
}

// Swaps a step (or check) with its neighbour of the same kind; derived nodes in between are re-derived on preview.
export function moveNode(nodes: StepsGraphNode[], id: string, direction: -1 | 1): StepsGraphNode[] {
  const index = nodes.findIndex((node) => node.id === id);
  if (index < 0 || !isStored(nodes[index])) return nodes;
  const kind = nodes[index].kind;
  let other = index + direction;
  while (other >= 0 && other < nodes.length && nodes[other].kind !== kind) other += direction;
  if (other < 0 || other >= nodes.length) return nodes;
  const next = [...nodes];
  [next[index], next[other]] = [next[other], next[index]];
  return next;
}

// Patches the raw entry; an `undefined` value removes the key (e.g. mode back to the class default).
function patched(entry: Json | undefined, patch: Json): Json {
  const next: Json = { ...(entry ?? {}) };
  for (const [key, value] of Object.entries(patch)) {
    if (value === undefined) delete next[key];
    else next[key] = value;
  }
  return next;
}

export function updateStep(nodes: StepsGraphNode[], id: string, patch: Json): StepsGraphNode[] {
  return nodes.map((node) => (node.id === id && node.kind === "step" ? { ...node, step: patched(node.step, patch) } : node));
}

export function updateCheck(nodes: StepsGraphNode[], id: string, patch: Json): StepsGraphNode[] {
  return nodes.map((node) => (node.id === id && node.kind === "check" ? { ...node, check: patched(node.check, patch) } : node));
}

// --- Rendering on the flow builder's canvas (FlowNode): one flow node per graph node, chained in order. ---

export type NodeBadge = { label: string; kind: BadgeKind };

export type StepsCanvasNode = FlowDefinitionNode & { subLabel: string; badges: NodeBadge[] };

const CLASS_TEXT: Record<string, string> = { change: "Change", deliver: "Deliver", read_only: "Read-only" };

function approvalText(node: StepsGraphNode): [string, string] {
  if (node.reason === "capability_class") {
    return ["User confirms first", `${CLASS_TEXT[node.capability_class ?? ""] ?? node.capability_class ?? ""} class`];
  }
  return ["Approval", `${node.tool ?? "This tool"} needs an approval`];
}

export function canvasNode(node: StepsGraphNode): StepsCanvasNode {
  const base = { id: node.id, config: {} };
  switch (node.kind) {
    case "start":
      return { ...base, type: "trigger", label: "Start", subLabel: "Phase starts", badges: [] };
    case "result":
      return { ...base, type: "output", label: "Result", subLabel: "Answer", badges: [] };
    case "approval": {
      const [label, subLabel] = approvalText(node);
      return { ...base, type: "approval", label, subLabel, badges: [] };
    }
    case "step": {
      const tool = text(node.step?.tool) || node.tool || "";
      const badges: NodeBadge[] = [
        { label: node.mode === "strict" ? "Strict" : "Guided", kind: node.mode === "strict" ? "active" : "running" },
      ];
      if (node.required === false) badges.push({ label: "Optional", kind: "neutral" });
      if (node.allowed === false) badges.push({ label: "Not in tool policy", kind: "danger" });
      return {
        ...base, type: "tool_step", label: node.label || tool || "Step", subLabel: tool || "No tool", badges,
      };
    }
    default: {
      const type = text(node.check?.type) || node.type || "";
      return {
        ...base,
        type: "evaluation",
        label: node.description || text(node.check?.description) || (type ? checkTypeLabel(type) : "Check"),
        subLabel: type ? `Check · ${checkTypeLabel(type)}` : "Check",
        badges: [node.blocking ? { label: "Blocking", kind: "danger" } : { label: "Reminder", kind: "neutral" }],
      };
    }
  }
}

export function canvasEdges(nodes: StepsGraphNode[]): FlowDefinitionEdge[] {
  return nodes.slice(1).map((node, index) => ({
    id: `${nodes[index].id}->${node.id}`,
    from_node_id: nodes[index].id,
    to_node_id: node.id,
  }));
}
