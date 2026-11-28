// The stored phased definition; backend workflow_runs/graph.py validates it.

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

export type FieldIssue = { path: string; message: string };

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
  workItemFields?: { key: string; label: string; kind: "enum" | "text" | "number" | "list"; values?: string[] }[];
};

export type NodePatch = { label?: string; config?: Record<string, unknown> };

export type EdgePatch = Partial<Pick<DefEdge, "when" | "max_iterations" | "label">>;
