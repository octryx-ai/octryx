import { useId, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import { OptionCards } from "../settingsKit/SettingsKit";
import type { ApprovalPolicy, ToolInfo } from "./toolApprovalsModel";
import { RISK_LABEL, policySummary, toolLabel } from "./toolApprovalsModel";
import { UNATTENDED_WARNING, unattendedToolProblem } from "../securityControls/securityControlsModel";
import "../securityControls/securityControls.css";

function ToolPicker({ label, values, tools, onChange, testId }: {
  label: string;
  values: string[];
  tools: ToolInfo[];
  onChange: (next: string[]) => void;
  testId: string;
}) {
  const [pick, setPick] = useState("");
  const available = tools.filter((tool) => !values.includes(tool.name));
  return (
    <div className="admin-panel__field">
      <span>{label}</span>
      <div className="sk-chips" data-testid={testId}>
        {values.map((name) => (
          <span key={name} className="admin-policy-chip admin-policy-chip--secondary sk-chip-removable">
            <span>{toolLabel(name)}</span>
            <button type="button" className="sk-chip-remove" aria-label={`Remove ${toolLabel(name)}`}
              onClick={() => onChange(values.filter((item) => item !== name))}>×</button>
          </span>
        ))}
        {values.length === 0 ? <span className="sk-muted">None</span> : null}
      </div>
      <div className="sk-row">
        <select className="admin-users__toolbar-select" value={pick} aria-label={`${label}: tool`} data-testid={`${testId}-select`}
          onChange={(event) => setPick(event.target.value)}>
          <option value="">Choose a tool</option>
          {available.map((tool) => <option key={tool.name} value={tool.name}>{toolLabel(tool.name)} · {RISK_LABEL[tool.risk] ?? tool.risk}</option>)}
        </select>
        <button type="button" className="admin-panel__action-btn" disabled={!pick} data-testid={`${testId}-add`}
          onClick={() => { onChange([...values, pick]); setPick(""); }}>Add</button>
      </div>
    </div>
  );
}

// Tools a run no person started may use to write without an approval: the platform default's alone. Any tool
// name or MCP capability key the server accepts can be typed; the known tools are suggested.
function UnattendedTools({ values, tools, onChange }: { values: string[]; tools: ToolInfo[]; onChange: (next: string[]) => void }) {
  const [name, setName] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const listId = useId();
  const inputId = useId();
  const add = () => {
    const why = unattendedToolProblem(name, values);
    setProblem(why);
    if (why) return;
    onChange([...values, name.trim()]);
    setName("");
  };
  return (
    <div className="admin-panel__field" data-testid="approval-unattended">
      <label htmlFor={inputId}>Unattended runs may use without approval</label>
      <p className="sk-warn" role="note">{UNATTENDED_WARNING}</p>
      <div className="sk-chips" data-testid="approval-unattended-list">
        {values.map((value) => (
          <span key={value} className="admin-policy-chip admin-policy-chip--secondary sk-chip-removable">
            <span>{toolLabel(value)}</span>
            <button type="button" className="sk-chip-remove" aria-label={`Remove ${toolLabel(value)}`}
              onClick={() => onChange(values.filter((item) => item !== value))}>×</button>
          </span>
        ))}
        {values.length === 0 ? <span className="sk-muted">None: every external write of an unattended run waits for approval.</span> : null}
      </div>
      <div className="sk-row">
        <input id={inputId} className="admin-panel__input sec-unattended__input" list={listId} value={name} placeholder="Tool name, e.g. add_jira_comment"
          data-testid="approval-unattended-input" autoComplete="off"
          onChange={(event) => { setName(event.target.value); setProblem(null); }}
          onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); add(); } }} />
        <datalist id={listId}>
          {tools.filter((tool) => !values.includes(tool.name)).map((tool) => (
            <option key={tool.name} value={tool.name}>{toolLabel(tool.name)} · {RISK_LABEL[tool.risk] ?? tool.risk}</option>
          ))}
        </datalist>
        <button type="button" className="admin-panel__action-btn" data-testid="approval-unattended-add" onClick={add}>Add</button>
      </div>
      {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
    </div>
  );
}

// Tool approvals for the platform default or one Workspace: a Workspace inherits the default
// or adds to it; the default and the additions name the risks that ask a person, the tools that always ask and the
// tools that never ask (they run their own approval). The same drawer opens from Workspace → Rules.
export function ApprovalPolicyDrawer({ title, workspace, mode: initialMode, policy, defaults, risks, tools, busy, problem,
  onClose, onSave }: {
  title: string;
  workspace: boolean;
  mode: "inherit" | "add";
  policy: ApprovalPolicy;
  defaults: ApprovalPolicy;
  risks: string[];
  tools: ToolInfo[];
  busy: boolean;
  problem: string | null;
  onClose: () => void;
  onSave: (mode: "inherit" | "add", policy: ApprovalPolicy) => void;
}) {
  const { openAdminTab } = useAdminNavigation();
  const [mode, setMode] = useState(initialMode);
  const [draft, setDraft] = useState(policy);
  const editing = !workspace || mode === "add";
  const toggleRisk = (risk: string, on: boolean) =>
    setDraft({ ...draft, require_for_risks: on ? [...draft.require_for_risks, risk] : draft.require_for_risks.filter((item) => item !== risk) });

  return (
    <SettingsDrawer eyebrow="Tool approvals" title={title} size="detail" onClose={onClose}
      footer={(
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy}
            data-testid="approval-save" onClick={() => onSave(mode, workspace ? { ...draft, exempt_tools: [] } : draft)}>Save</button>
        </>
      )}>
      <div className="sk-page" data-testid="approval-drawer">
        {workspace ? (
          <OptionCards name={`approval-mode-${title}`} label="Approvals for this Workspace" value={mode} onChange={setMode}
            options={[
              { value: "inherit", title: "Inherit platform default", desc: policySummary(defaults) },
              { value: "add", title: "Add to the default", desc: "Everything from the default, plus the rules below." },
            ]} />
        ) : null}
        {editing ? (
          <>
            <div className="admin-panel__field">
              <span>Ask a person for risk</span>
              <div className="sk-row" data-testid="approval-risks">
                {risks.map((risk) => {
                  const inherited = workspace && defaults.require_for_risks.includes(risk);
                  return (
                    <label key={risk} className="admin-panel__checkbox">
                      <input type="checkbox" checked={inherited || draft.require_for_risks.includes(risk)} disabled={inherited}
                        onChange={(event) => toggleRisk(risk, event.target.checked)} />
                      {RISK_LABEL[risk] ?? risk}{inherited ? " (default)" : ""}
                    </label>
                  );
                })}
              </div>
            </div>
            <ToolPicker label="Always ask for these tools" values={draft.require_for_tools} tools={tools} testId="approval-always"
              onChange={(next) => setDraft({ ...draft, require_for_tools: next })} />
            {/* A Workspace can only add: exemptions are the platform default's alone (settings review). */}
            {!workspace ? (
              <ToolPicker label="Never ask for these tools (they run their own approval)" values={draft.exempt_tools} tools={tools}
                testId="approval-never" onChange={(next) => setDraft({ ...draft, exempt_tools: next })} />
            ) : null}
            {!workspace ? (
              <UnattendedTools values={draft.unattended_allowed_tools ?? []} tools={tools}
                onChange={(next) => setDraft({ ...draft, unattended_allowed_tools: next })} />
            ) : null}
          </>
        ) : null}
        <p className="sk-hint">
          Approvers: set in <button type="button" className="sk-link" onClick={() => openAdminTab("approvalRule")}>Approval rule</button>.
        </p>
        {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
      </div>
    </SettingsDrawer>
  );
}
