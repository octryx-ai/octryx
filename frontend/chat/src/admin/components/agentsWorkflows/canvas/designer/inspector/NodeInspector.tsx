import type { DefEdge, DefNode, DesignerCatalog, FieldIssue, NodePatch } from "../types";
import { Problems, TextField } from "./fields";
import { record, text, type Config } from "./inspectorValues";
import { DESIGNER_STEP_ID } from "./nodeDefaults";
import { Form } from "./NodeInspectorForm";
import { ON_OPEN_HIGH_KEY } from "./onOpenHigh";
import { issuesAt, setIn } from "./patch";

type Props = {
  node: DefNode;
  nodes: DefNode[];
  edges: DefEdge[];
  catalog: DesignerCatalog;
  editable: boolean;
  issues: FieldIssue[];
  onChange(patch: NodePatch): void;
  onRoute?(when: string, target: string | null): void;
};

function withStepIds(config: Config): Config {
  const contract = record(config.workflow_contract);
  let next = config;
  for (const key of ["workflow_id", "workflow_class"]) {
    if (!text(contract[key]) && !text(config[key])) next = setIn(next, `workflow_contract.${key}`, DESIGNER_STEP_ID);
  }
  return next;
}

const SHOWN: Record<string, string[]> = {
  phase: ["config.agent", "config.workflow_contract", "config.tool_policy", "config.result_values"],
  gate: ["config.checks", "config.phase"],
  decision: ["config.source", "config.options", "config.check", "config.field", "config.operator", "config.value"],
  approval: ["config.decider", "config.title", "config.summary"],
  user_confirmation: ["config.subject", `config.${ON_OPEN_HIGH_KEY}`],
  user_conversation: ["config.question"],
  watch: ["config.conditions"],
  platform_action: ["config.action", "config.tool", "config.arguments"],
  sub_workflow: ["config.workflow_key"],
  outcome: ["config.outcome"],
  parallel_work: ["config.plan", "config.roles", "config.parallel"],
};

export function NodeInspector({ node, nodes, edges, catalog, editable, issues, onChange, onRoute }: Props) {
  const shown = ["label", ...(SHOWN[node.type] ?? [])];
  const elsewhere = issues.filter((issue) => !shown.some((path) => issue.path === path || issue.path.startsWith(`${path}.`)));
  // Steps made before the designer set step ids get them with their next change.
  const base = node.type === "phase" ? withStepIds(node.config ?? {}) : node.config ?? {};
  const setAll = (changes: [string, unknown][]) =>
    onChange({ config: changes.reduce((config, [path, value]) => setIn(config, path, value), base) });
  const set = (path: string, value: unknown) => setAll([[path, value]]);
  return (
    <div className="aw-inspector dsi" data-testid="node-inspector">
      <Problems issues={elsewhere} />
      <TextField label="Name" value={node.label} disabled={!editable} issues={issuesAt(issues, "label")}
        onChange={(label) => onChange({ label })} />
      {/* Keyed by node so a different box starts with fresh open/closed state. */}
      <Form key={node.id} node={node} nodes={nodes} edges={edges} catalog={catalog} editable={editable} issues={issues}
        set={set} setAll={setAll} replace={(config) => onChange({ config })} onRoute={onRoute} />
    </div>
  );
}
