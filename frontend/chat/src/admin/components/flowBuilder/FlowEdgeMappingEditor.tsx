import type { Edge } from "@xyflow/react";
import type { FlowDefinitionNode } from "./flowBuilderTypes";
import { storedCondition } from "./flowCanvasMapping";
import { branchCondition, edgeBranch, matchedBranchNames } from "./flowBranchConnections";
import { ruleBranch, type RouterRule } from "./flowRouterRule";
import "./flowConditional.css";

export type FlowEdgeData = {
  sourceField?: string;
  targetField?: string;
  condition?: string;
  // Authored values this editor does not edit; kept so a load → save round trip is lossless.
  conditionSource?: unknown;
  extra?: Record<string, unknown>;
};

type FlowEdgeMappingEditorProps = {
  edge: Edge<FlowEdgeData>;
  nodes: FlowDefinitionNode[];
  onUpdate: (edgeId: string, data: FlowEdgeData) => void;
  onDelete: () => void;
};

function fieldKeys(
  nodes: FlowDefinitionNode[],
  nodeId: string,
  schemaKey: "input_schema" | "output_schema",
): string[] {
  const node = nodes.find((item) => item.id === nodeId);
  const schema = node?.[schemaKey];
  return schema ? Object.keys(schema) : [];
}

// The branches an If / else step can pick, in rule order, then its Otherwise branch.
function routerBranches(node: FlowDefinitionNode | undefined): { name: string; label: string }[] {
  if (node?.type !== "router") return [];
  // Only rule objects name a branch; other saved items are left to the inspector's warning.
  const rules = Array.isArray(node.config?.routes)
    ? (node.config.routes as unknown[]).filter((rule): rule is RouterRule => Boolean(rule) && typeof rule === "object" && !Array.isArray(rule))
    : [];
  const branches: { name: string; label: string }[] = [];
  rules.forEach((rule, index) => {
    const name = ruleBranch(rule && typeof rule === "object" ? rule : {});
    if (!branches.some((item) => item.name === name)) branches.push({ name, label: `Rule ${index + 1} · ${name}` });
  });
  const otherwise = String(node.config?.default_route || "default");
  const existing = branches.find((item) => item.name === otherwise);
  if (existing) existing.label = `${existing.label} (also Otherwise)`;
  else branches.push({ name: otherwise, label: `Otherwise · ${otherwise}` });
  return branches;
}

const FALLBACK = "__fallback__";
const CUSTOM = "__custom__";
const MULTIPLE = "__multiple__";

type Branch = { name: string; label: string };

// The edge data a branch choice writes, or null for the kept-as-saved entries.
function branchChoicePatch(value: string, branches: Branch[]): FlowEdgeData | null {
  if (value === CUSTOM || value === MULTIPLE) return null;
  if (value === FALLBACK) return { condition: "" };
  // `route:<name>` also runs for a branch literally named "route:<name>"; when that one
  // is declared too, `{route: <name>}` keeps the choice to exactly this branch.
  if (branches.some((branch) => branch.name === `route:${value}`)) {
    const exact = { route: value };
    return { condition: JSON.stringify(exact), conditionSource: exact };
  }
  return { condition: branchCondition({ kind: "branch", name: value }) };
}

function FieldOptions({ id, fields }: { id: string; fields: string[] }) {
  return (
    <datalist id={id}>
      {fields.map((field) => (
        <option key={field} value={field} />
      ))}
    </datalist>
  );
}

type BranchOptionsProps = { choice: string; branches: Branch[]; declared: string[]; current: ReturnType<typeof edgeBranch> };

function BranchOptions({ choice, branches, declared, current }: BranchOptionsProps) {
  return (
    <>
      {branches.map((branch) => (
        <option key={branch.name} value={branch.name}>
          {branch.label}
        </option>
      ))}
      <option value={FALLBACK}>Any branch without its own connection</option>
      {choice === MULTIPLE ? (
        <option value={MULTIPLE}>
          Multiple branches: {declared.map((name) => `“${name}”`).join(" and ")} (kept as saved)
        </option>
      ) : null}
      {choice === CUSTOM ? (
        <option value={CUSTOM}>
          {current.kind === "branch" ? `Branch “${current.name}” (no rule picks it)` : "Custom condition (kept as saved)"}
        </option>
      ) : null}
    </>
  );
}

// A connection out of an If / else step: choose the branch it continues on. A condition in
// another form stays as saved ("Custom") until the author picks a branch explicitly.
function edgeBranchChoice(nodes: FlowDefinitionNode[], source: string, data: FlowEdgeData) {
  const branches = routerBranches(nodes.find((item) => item.id === source));
  const saved = storedCondition(data);
  const current = edgeBranch(saved);
  // A route:foo string runs for a branch literally named "route:foo" and for "foo". With exactly
  // one of them declared it shows that branch; with both it runs for both, so it stays "Multiple
  // branches (kept as saved)" until the author picks one branch explicitly.
  const declared = current.kind === "branch" ? (matchedBranchNames(saved) ?? []).filter((name) => branches.some((item) => item.name === name)) : [];
  const choice = current.kind === "fallback" ? FALLBACK : declared.length === 1 ? declared[0] : declared.length > 1 ? MULTIPLE : CUSTOM;
  return { branches, current, declared, choice };
}

export function FlowEdgeMappingEditor({
  edge,
  nodes,
  onUpdate,
  onDelete,
}: FlowEdgeMappingEditorProps) {
  const sourceFields = fieldKeys(nodes, edge.source, "output_schema");
  const targetFields = fieldKeys(nodes, edge.target, "input_schema");
  const data = edge.data ?? {};
  const sourceListId = `${edge.id}-source-fields`;
  const targetListId = `${edge.id}-target-fields`;

  function update(patch: FlowEdgeData) {
    onUpdate(edge.id, { ...data, ...patch });
  }

  const { branches, current, declared, choice } = edgeBranchChoice(nodes, edge.source, data);
  const pickBranch = (value: string) => {
    const patch = branchChoicePatch(value, branches);
    if (patch) update(patch);
  };

  return (
    <div className="flow-canvas__edge-editor">
      <div className="flow-canvas__edge-editor-head">
        <span>{edge.source} {"->"} {edge.target}</span>
        <button type="button" onClick={onDelete}>Delete</button>
      </div>
      <label>
        <span>Source field</span>
        <input list={sourceListId} value={data.sourceField ?? ""} placeholder={sourceFields[0] ?? "field"}
          onChange={(event) => update({ sourceField: event.target.value })} />
        <FieldOptions id={sourceListId} fields={sourceFields} />
      </label>
      <label>
        <span>Target field</span>
        <input list={targetListId} value={data.targetField ?? ""} placeholder={targetFields[0] ?? "field"}
          onChange={(event) => update({ targetField: event.target.value })} />
        <FieldOptions id={targetListId} fields={targetFields} />
      </label>
      {branches.length ? (
        <label>
          <span>Runs for branch</span>
          <select value={choice} onChange={(event) => pickBranch(event.target.value)}>
            <BranchOptions choice={choice} branches={branches} declared={declared} current={current} />
          </select>
        </label>
      ) : null}
      {!branches.length || choice === CUSTOM ? (
        <label>
          <span>Condition</span>
          <input value={data.condition ?? ""} placeholder="route:approved"
            onChange={(event) => update({ condition: event.target.value })} />
        </label>
      ) : null}
    </div>
  );
}
