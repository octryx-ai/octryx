import { useCallback, useEffect, useState } from "react";

import { StatusLabel } from "../../layout/StatusLabel";
import { loadDeviceRunsPolicy, saveDeviceRunsPolicy } from "./devicesApi";
import {
  HARD_RULES_LINE,
  MAX_ALLOWED_TOOLS,
  TOOL_DEFAULT_ROWS,
  allowedToolProblem,
  changedCount,
  isChanged,
  readToolDefaults,
  showsAllowedTools,
  toolDefaultsErrorField,
  toolDefaultsErrorText,
  toolDefaultsPatch,
  type ToolDefaults,
  type ToolDefaultsView,
} from "./toolDefaultsModel";
import "../../admin/components/settingsKit/settingsKit.css";
import "./devices.css";

// Workspace settings › Coding tools & devices › "Tool defaults" (allow by default; blocking is an
// admin option): what a device session may do without a rule allowing it, one switch per key of
// `device_runs.tool_defaults`, saved through the device-runs PUT. Members see it read-only. An answer without
// `tool_defaults_effective` shows nothing.
type FieldProblem = { field: string; text: string } | null;

export function ToolDefaultsCard({ projectId }: { projectId: string }) {
  const [view, setView] = useState<ToolDefaultsView | null>(null);
  const [loadProblem, setLoadProblem] = useState<string | null>(null);
  const [problem, setProblem] = useState<FieldProblem>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setView(readToolDefaults(await loadDeviceRunsPolicy(projectId)));
      setLoadProblem(null);
    } catch {
      setLoadProblem("The tool defaults could not be loaded.");
    }
  }, [projectId]);
  useEffect(() => { void load(); }, [load]);

  if (!view) return loadProblem ? <p className="sk-err" role="alert">{loadProblem}</p> : null;
  const editable = view.canEdit && view.policyValid;
  const effective = view.effective;
  const changed = changedCount(effective);

  /** Saves one change; true when the server took it. A refusal stands at the field it names. */
  const save = async (field: string, change: Partial<ToolDefaults>): Promise<boolean> => {
    setBusy(true);
    setProblem(null);
    setSaved(null);
    try {
      const next = readToolDefaults(await saveDeviceRunsPolicy(projectId, toolDefaultsPatch(change)));
      if (next) setView(next);
      setSaved(field);
      return true;
    } catch (error) {
      const at = toolDefaultsErrorField(error);
      setProblem({ field: at === "section" ? field : at, text: toolDefaultsErrorText(error) });
      return false;
    } finally {
      setBusy(false);
    }
  };
  const problemAt = (field: string) => (problem?.field === field ? problem.text : null);

  return (
    <section className="admin-panel__card" aria-label="Tool defaults" data-testid="tool-defaults">
      <div className="admin-panel__section-header">
        <span>Tool defaults</span>
        <StatusLabel label={changed ? `${changed} changed` : "All defaults"} tone="neutral" testId="tool-defaults-changed" />
      </div>
      <p className="sk-hint">
        What device sessions and runs may do without a rule allowing it. By default everything is allowed and logged
        in the run; each switch blocks it instead.
        {!editable ? " Only the Workspace's admins and owners change these settings." : ""}
      </p>
      <div>
        {TOOL_DEFAULT_ROWS.map((row) => {
          const id = `tool-default-${row.key}`;
          const differs = isChanged(effective, row.key);
          const error = problemAt(row.key);
          const allowedTools = row.key === "unknown_tools" && showsAllowedTools(effective) ? (
            <AllowedToolsField tools={effective.allowed_tools} disabled={!editable} busy={busy} problem={problemAt("allowed_tools")}
              onSave={(tools) => save("allowed_tools", { allowed_tools: tools })} />
          ) : null;
          return (
            <div key={row.key} className="device-setting tool-default" data-testid={id} data-changed={differs ? "true" : undefined}>
              <div className="tool-default__text">
                <label htmlFor={id}><b>{row.label}</b></label>
                <p>{row.help}</p>
                {error ? <p className="sk-err" role="alert">{error}</p> : null}
                {saved === row.key && !error ? <p className="admin-panel__success" role="status">Saved. It applies to the next tool call.</p> : null}
                {allowedTools}
              </div>
              <div className="tool-default__control">
                {differs ? <StatusLabel label="Changed" tone="neutral" testId={`${id}-changed`} /> : <span className="sk-muted">Default</span>}
                <select id={id} className="admin-panel__input" value={effective[row.key]} disabled={!editable || busy}
                  aria-invalid={error ? true : undefined}
                  onChange={(event) => void save(row.key, { [row.key]: event.target.value } as Partial<ToolDefaults>)}>
                  {row.options.map((option, index) => (
                    <option key={option.value} value={option.value}>{index === 0 ? `${option.label} (default)` : option.label}</option>
                  ))}
                </select>
              </div>
            </div>
          );
        })}
      </div>
      <p className="sk-hint" data-testid="tool-defaults-hard-rules">{HARD_RULES_LINE}</p>
    </section>
  );
}

/** The tools that stay allowed while tools without a rule are denied: removable chips and an input. */
function AllowedToolsField({ tools, disabled, busy, problem, onSave }: {
  tools: string[];
  disabled: boolean;
  busy: boolean;
  problem: string | null;
  onSave: (tools: string[]) => Promise<boolean>;
}) {
  const [draft, setDraft] = useState("");
  const [typed, setTyped] = useState<string | null>(null);
  const add = async () => {
    const reason = allowedToolProblem(draft, tools);
    if (reason) {
      setTyped(reason);
      return;
    }
    if (await onSave([...tools, draft.trim()])) setDraft("");
  };
  const shown = typed ?? problem;

  return (
    <div className="tool-default__allowed" data-testid="allowed-tools">
      <b>Still allowed</b>
      <p>Exact tool names, for example <code>web.run</code> or <code>mcp__github__create_issue</code>; at most {MAX_ALLOWED_TOOLS}.</p>
      <div className="sk-chips">
        {tools.map((tool) => (
          <span key={tool} className="admin-policy-chip admin-policy-chip--secondary sk-chip-removable">
            <span className="device-mono">{tool}</span>
            {!disabled ? (
              <button type="button" className="sk-chip-remove" aria-label={`Remove ${tool}`} disabled={busy}
                onClick={() => void onSave(tools.filter((item) => item !== tool))}>×</button>
            ) : null}
          </span>
        ))}
        {tools.length === 0 ? <span className="sk-muted">No tool: every tool without a rule is refused.</span> : null}
      </div>
      {!disabled ? (
        <div className="sk-row tool-default__add">
          <input className="admin-users__toolbar-input" value={draft} placeholder="web.run" aria-label="Add an allowed tool"
            aria-invalid={shown ? true : undefined} data-testid="allowed-tools-input" disabled={busy || tools.length >= MAX_ALLOWED_TOOLS}
            onChange={(event) => { setDraft(event.target.value); setTyped(null); }}
            onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void add(); } }} />
          <button type="button" className="admin-panel__action-btn" disabled={busy || !draft.trim()}
            data-testid="allowed-tools-add" onClick={() => void add()}>Add</button>
        </div>
      ) : null}
      {shown ? <p className="sk-err" role="alert">{shown}</p> : null}
    </div>
  );
}
