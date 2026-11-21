// The side panel for one arrow: for which result it is taken, and for a way back how often at most.
// Pure: the arrow, the workflow and the catalog come in; a patch goes out. The kind of arrow is drawn, not chosen here.
import type { DefEdge, DefNode, DesignerCatalog, EdgePatch, FieldIssue } from "../types";
import { NumberField, Problems, SelectField, TextField } from "./fields";
import { exitName, kindName } from "./labels";
import { edgeChoices, issuesAt } from "./patch";

type Props = {
  edge: DefEdge;
  edges: DefEdge[];
  nodes: DefNode[];
  catalog: DesignerCatalog;
  editable: boolean;
  issues: FieldIssue[];
  onChange(patch: EdgePatch): void;
};

const boxName = (node: DefNode | undefined) => (node ? node.label || kindName(node.type) : "a removed box");

export function EdgeInspector({ edge, edges, nodes, catalog, editable, issues, onChange }: Props) {
  const source = nodes.find((node) => node.id === edge.source);
  const target = nodes.find((node) => node.id === edge.target);
  const choices = edgeChoices(source, catalog);
  const taken = new Set(edges.filter((other) => other.id !== edge.id && other.source === edge.source).map((other) => other.when));
  const isLoop = edge.kind === "loop";
  return (
    <div className="aw-inspector dsi" data-testid="edge-inspector">
      <p className="dsi-route">
        From <strong>{boxName(source)}</strong> to <strong>{boxName(target)}</strong>
      </p>
      <Problems issues={issues.filter((issue) => !["when", "max_iterations", "label"].includes(issue.path))} />
      {choices === null ? (
        <p className="admin-panel__hint">{boxName(source)} has one way out, so this arrow is always taken.</p>
      ) : (
        <SelectField label="Taken when the result is" value={edge.when ?? ""} disabled={!editable}
          issues={issuesAt(issues, "when")}
          hint={choices.length ? "Each result needs its own arrow." : "This box has no results to choose from yet."}
          options={choices.map((value) => ({
            value, label: taken.has(value) ? `${exitName(value)} (already has an arrow)` : exitName(value) }))}
          onChange={(value) => onChange({ when: value || null })} />
      )}
      {isLoop ? (
        <NumberField label="Goes back at most" min={1} value={edge.max_iterations} disabled={!editable}
          issues={issuesAt(issues, "max_iterations")} hint="Times. After that the run takes the other way."
          onChange={(value) => onChange({ max_iterations: value })} />
      ) : null}
      <TextField label="Text on the arrow (optional)" value={edge.label ?? ""} disabled={!editable}
        placeholder={edge.when ? exitName(edge.when) : undefined} issues={issuesAt(issues, "label")}
        onChange={(label) => onChange({ label: label || undefined })} />
    </div>
  );
}
