// The designer's side panel for one box: one form per kind of box, in plain words.
// Pure: the node, the workflow's other nodes, the catalog and the problems come in; a patch with the complete new
// config goes out (the canvas core keeps it undoable). Problems show at their field; the rest at the top.
// A condition also sets where each of its results leads (``onRoute``, agreed with octryx-work).
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
  /** A condition's result ``when`` now leads to ``target`` (null: no arrow). The canvas core creates, moves or
   * deletes that next arrow. Without it the form shows where each result leads, read only. */
  onRoute?(when: string, target: string | null): void;
  /** The workflow's key: some settings name its default (a confirmation's ``on_open_high``). */
  workflowKey?: string;
};

function withStepIds(config: Config): Config {
  const contract = record(config.workflow_contract);
  let next = config;
  for (const key of ["workflow_id", "workflow_class"]) {
    if (!text(contract[key]) && !text(config[key])) next = setIn(next, `workflow_contract.${key}`, DESIGNER_STEP_ID);
  }
  return next;
}

/** The field paths a form shows itself; problems elsewhere go to the top of the panel. */
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


export function NodeInspector({ node, nodes, edges, catalog, editable, issues, onChange, onRoute, workflowKey }: Props) {
  const shown = ["label", ...(SHOWN[node.type] ?? [])];
  const elsewhere = issues.filter((issue) => !shown.some((path) => issue.path === path || issue.path.startsWith(`${path}.`)));
  // An agent step without its technical name (made before the designer set it) gets it with its next change.
  const base = node.type === "phase" ? withStepIds(node.config ?? {}) : node.config ?? {};
  const setAll = (changes: [string, unknown][]) =>
    onChange({ config: changes.reduce((config, [path, value]) => setIn(config, path, value), base) });
  const set = (path: string, value: unknown) => setAll([[path, value]]);
  return (
    <div className="aw-inspector dsi" data-testid="node-inspector">
      <Problems issues={elsewhere} />
      <TextField label="Name" value={node.label} disabled={!editable} issues={issuesAt(issues, "label")}
        onChange={(label) => onChange({ label })} />
      {/* key: a different box starts with its own open/closed lists */}
      <Form key={node.id} node={node} nodes={nodes} edges={edges} catalog={catalog} editable={editable} issues={issues}
        set={set} setAll={setAll} replace={(config) => onChange({ config })} onRoute={onRoute} workflowKey={workflowKey} />
    </div>
  );
}
