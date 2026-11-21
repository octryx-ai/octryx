// Settings of a node of a phase (its steps and checks), shown in the editor's side panel. A step edits its
// `source_steps` entry (tool, evidence label, required, strict / guided), a check its `checks` entry (type,
// description, blocking, params); derived nodes explain themselves. The panel owner decides what an edit changes: a
// new step or check is a local draft until "Add …", an existing one is part of the workflow draft (and previewed).
// Move earlier / later and Remove are the panel's footer actions (StepsWorkflowEditor), not part of these fields.
import { useEffect, useState } from "react";

import { TOOL_LIST_CHECK_TYPES, checkTypeLabel } from "./checkTypeLabels";
import type { StepsGraphNode, StepsGraphView } from "./stepsGraphModel";

type StepsInspectorProps = {
  node: StepsGraphNode;
  view: StepsGraphView;
  editable: boolean;
  toolNames: string[];
  onStep: (patch: Record<string, unknown>) => void;
  onCheck: (patch: Record<string, unknown>) => void;
};

const text = (value: unknown) => (typeof value === "string" ? value : "");
const hasParams = (value: unknown) => Boolean(value && typeof value === "object" && Object.keys(value as object).length);
const MODE_WORDS: Record<string, string> = { strict: "Strict", guided: "Guided" };
const modeWord = (mode: string) => MODE_WORDS[mode] ?? mode;

function DerivedNote({ node }: { node: StepsGraphNode }) {
  const note =
    node.kind === "start" ? "The phase starts when the workflow reaches it."
      : node.kind === "result" ? "The answer. It is held while a blocking check or a strict step is not satisfied."
        : node.reason === "capability_class"
          ? "Change and Deliver workflows ask the user to confirm before they start. Set by the capability class."
          : `The tool ${node.tool ?? ""} declares that it needs an approval before it runs.`;
  return <p className="admin-panel__hint">{note} This node is derived from the definition and cannot be edited.</p>;
}

function ParamsField({ value, disabled, open = false, onChange }: {
  value: unknown; disabled: boolean; open?: boolean; onChange: (next: unknown) => void;
}) {
  const [draft, setDraft] = useState(JSON.stringify(value ?? {}, null, 2));
  const [problem, setProblem] = useState<string | null>(null);
  useEffect(() => setDraft(JSON.stringify(value ?? {}, null, 2)), [value]);
  const commit = () => {
    try {
      const parsed = JSON.parse(draft || "{}") as unknown;
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("Parameters must be a JSON object.");
      setProblem(null);
      onChange(parsed);
    } catch (error) {
      setProblem(error instanceof Error ? error.message : "Parameters must be a JSON object.");
    }
  };
  // The raw parameters sit behind "Technical details"; the fields people need are shown above them.
  return (
    <details className="ds-advanced" open={open || Boolean(problem)} data-testid="check-technical-details">
      <summary className="ds-advanced__summary">Technical details</summary>
      <label className="admin-panel__field">
        <span>Parameters (JSON)</span>
        <textarea className="admin-panel__input" rows={5} value={draft} disabled={disabled} onChange={(event) => setDraft(event.target.value)}
          onBlur={commit} />
        {problem ? <span className="admin-panel__error" role="alert">{problem}</span> : null}
      </label>
    </details>
  );
}

// The tools a tool check names (params.tools), as one comma-separated field; other parameters are kept.
function ToolsField({ params, disabled, toolNames, onChange }: {
  params: unknown; disabled: boolean; toolNames: string[]; onChange: (next: Record<string, unknown>) => void;
}) {
  const current = params && typeof params === "object" && !Array.isArray(params) ? (params as Record<string, unknown>) : {};
  const tools = Array.isArray(current.tools) ? current.tools.filter((item): item is string => typeof item === "string") : [];
  const [draft, setDraft] = useState(tools.join(", "));
  useEffect(() => setDraft(tools.join(", ")), [tools.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps
  const commit = () => {
    const next = draft.split(",").map((item) => item.trim()).filter(Boolean);
    if (next.join(",") === tools.join(",")) return;
    onChange({ ...current, tools: next });
  };
  return (
    <label className="admin-panel__field">
      <span>Tools</span>
      <input className="admin-panel__input" list="steps-inspector-check-tools" value={draft} disabled={disabled}
        placeholder="Tool names, separated by commas" onChange={(event) => setDraft(event.target.value)} onBlur={commit}
        data-testid="check-tools" />
      <datalist id="steps-inspector-check-tools">{toolNames.map((name) => <option key={name} value={name} />)}</datalist>
    </label>
  );
}

export function StepsInspector({ node, view, editable, toolNames, onStep, onCheck }: StepsInspectorProps) {
  if (node.derived || (node.kind !== "step" && node.kind !== "check")) return <div className="aw-inspector"><DerivedNote node={node} /></div>;
  if (node.kind === "step") {
    const step = node.step ?? {};
    const explicit = text(step.mode);
    const defaultMode = node.mode_explicit ? null : node.mode;
    return (
      <div className="aw-inspector" data-testid="steps-inspector">
        <label className="admin-panel__field">
          <span>Tool</span>
          <input list="steps-inspector-tools" value={text(step.tool)} disabled={!editable}
            onChange={(event) => onStep({ tool: event.target.value })} />
          <datalist id="steps-inspector-tools">{toolNames.map((name) => <option key={name} value={name} />)}</datalist>
        </label>
        <label className="admin-panel__field">
          <span>Evidence label</span>
          <input value={text(step.evidence_label)} disabled={!editable}
            onChange={(event) => onStep({ evidence_label: event.target.value || undefined })} />
        </label>
        <label className="admin-panel__field">
          <span>Mode</span>
          <select value={explicit} disabled={!editable} onChange={(event) => onStep({ mode: event.target.value || undefined })}>
            <option value="">{`Class default${defaultMode ? ` (${modeWord(defaultMode)})` : ""}`}</option>
            {view.stepModes.map((mode) => <option key={mode} value={mode}>{modeWord(mode)}</option>)}
          </select>
        </label>
        <label className="admin-panel__checkbox">
          <input type="checkbox" checked={step.required !== false} disabled={!editable}
            onChange={(event) => onStep({ required: event.target.checked ? undefined : false })} />
          <span>Required (an optional step is never checked)</span>
        </label>
        {node.allowed === false ? <p className="admin-panel__error">The workflow's tool policy does not allow this tool.</p> : null}
      </div>
    );
  }
  const check = node.check ?? {};
  const type = text(check.type);
  const advisory = view.advisoryCheckTypes.includes(type);
  return (
    <div className="aw-inspector" data-testid="steps-inspector">
      <label className="admin-panel__field">
        <span>Check type</span>
        <select value={type} disabled={!editable}
          onChange={(event) => onCheck({ type: event.target.value, ...(view.advisoryCheckTypes.includes(event.target.value) ? { blocking: false } : {}) })}>
          {view.checkTypes.map((item) => <option key={item} value={item}>{checkTypeLabel(item)}</option>)}
        </select>
      </label>
      <label className="admin-panel__field">
        <span>Description</span>
        <input value={text(check.description)} disabled={!editable} onChange={(event) => onCheck({ description: event.target.value })} />
      </label>
      <label className="admin-panel__checkbox">
        <input type="checkbox" checked={check.blocking === true} disabled={!editable || advisory}
          onChange={(event) => onCheck({ blocking: event.target.checked })} />
        <span>{advisory ? "Advisory only (a judge check never blocks)" : "Blocking: the turn ends not verified when it fails"}</span>
      </label>
      {TOOL_LIST_CHECK_TYPES.has(type) ? (
        <ToolsField params={check.params} disabled={!editable} toolNames={toolNames} onChange={(params) => onCheck({ params })} />
      ) : null}
      <ParamsField value={check.params} disabled={!editable} onChange={(params) => onCheck({ params })}
        open={!TOOL_LIST_CHECK_TYPES.has(type) && hasParams(check.params)} />
    </div>
  );
}
