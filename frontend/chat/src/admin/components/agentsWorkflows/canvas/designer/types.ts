// The workflow designer's one format: the phased definition as it is stored
// (flow version ``definition_json`` with ``execution_kind: "phased"``). backend/app/services/workflow_runs/graph.py
// validates it; the canvas core (model, catalog, groups, undo) and the side panel (node and edge inspectors) share
// these types.

export type NodeKind =
  | "start"
  | "phase"
  | "gate"
  | "decision"
  | "outcome"
  | "platform_action"
  | "user_conversation"
  | "user_confirmation"
  | "watch"
  | "approval"
  | "sub_workflow"
  | "review"
  | "pause"
  // Teamwork (WP-D): the coordinator's plan is run as items in parallel at run time; exits "done" or "replan".
  | "parallel_work";

export type DefNode = { id: string; type: NodeKind; label: string; config: Record<string, unknown> };

export type DefEdge = {
  id: string;
  source: string;
  target: string;
  kind: "next" | "loop";
  when: string | null;
  max_iterations: number | null;
  label?: string;
};

// A problem at one field of a node: ``path`` such as "config.workflow_contract.capability_class".
export type FieldIssue = { path: string; message: string };

// What the side panel offers to choose from (GET /api/v1/phased-workflows/catalog).
export type DesignerCatalog = {
  agents: { key: string; name: string; capability_ceiling: "read_only" | "change" | "deliver" }[];
  tools: string[];
  checkTypes: { type: string; label: string; params: string[] }[];
  gateCheckTypes: string[];
  workflows: { key: string; title: string }[];
  platformActions: { key: string; label: string; routes: string[] }[];
  confirmationSubjects: string[];
  watchConditions: string[];
  outcomes: string[];
  deciders: string[];
  // Fields of the work item a condition can compare (D2b2, decision check "field"); absent until the catalog has them.
  workItemFields?: { key: string; label: string; kind: "enum" | "text" | "number" | "list"; values?: string[] }[];
};

// A side-panel change: a new label and/or the node's complete new config.
export type NodePatch = { label?: string; config?: Record<string, unknown> };

export type EdgePatch = Partial<Pick<DefEdge, "when" | "max_iterations" | "label">>;
