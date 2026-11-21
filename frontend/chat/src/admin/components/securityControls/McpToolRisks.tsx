import { useCallback, useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import "../settingsKit/settingsKit.css";
import "./securityControls.css";
import {
  MCP_RISKS,
  MCP_RISK_HINT,
  mcpToolBindings,
  riskPatch,
  riskSavedText,
  type McpRisk,
  type McpToolBinding,
} from "./securityControlsModel";

const composition = (workspaceId: string) =>
  `/admin/chat/api/panel/projects/${encodeURIComponent(workspaceId)}/workspace-composition`;

// The risk class of each mirrored tool of one remote MCP server in this Workspace: a select per tool writes
// `policy_config.risk` on the tool's Workspace capability binding (the server keeps every mirror-owned key). The class
// decides which runs may call the tool; one quiet line says how.
export function McpToolRisks({ workspaceId, serverName }: { workspaceId: string; serverName: string }) {
  const [rows, setRows] = useState<McpToolBinding[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);

  const read = useCallback((payload: unknown) => {
    setRows(mcpToolBindings((payload as { bindings?: unknown } | null)?.bindings, serverName));
  }, [serverName]);

  useEffect(() => {
    let current = true;
    setRows(null);
    setProblem(null);
    setSaved(null);
    readJson<unknown>(composition(workspaceId)).then(
      (payload) => { if (current) read(payload); },
      () => { if (current) setProblem("The tools of this server could not be loaded."); },
    );
    return () => { current = false; };
  }, [workspaceId, read]);

  const change = async (row: McpToolBinding, risk: McpRisk) => {
    setSaving(row.id);
    setProblem(null);
    setSaved(null);
    try {
      read(await readJson<unknown>(`${composition(workspaceId)}/bindings/${encodeURIComponent(row.id)}`, {
        method: "PUT", body: JSON.stringify(riskPatch(row, risk)),
      }));
      setSaved(riskSavedText(row.tool, risk));
    } catch (failure) {
      setProblem(`Not saved: ${failure instanceof Error && failure.message ? failure.message : "the request was refused"}.`);
    } finally {
      setSaving(null);
    }
  };

  return (
    <section className="admin-mcp-risks" aria-label="Tool risk" data-testid="mcp-tool-risks">
      <h3 className="admin-mcp-risks__title">Tool risk</h3>
      <p className="sk-hint">{MCP_RISK_HINT}</p>
      {rows === null && !problem ? <p className="sk-hint" role="status">Loading the tools…</p> : null}
      {rows && rows.length === 0 ? (
        <p className="sk-hint">No tool of this server is mirrored into this Workspace yet; connect it to list its tools.</p>
      ) : null}
      {rows && rows.length ? (
        <ul className="admin-mcp-risks__list">
          {rows.map((row) => (
            <li key={row.id} className="admin-mcp-risks__row">
              <span className="admin-mcp-risks__tool">{row.tool}</span>
              <span className="admin-mcp-risks__state">{row.enabled ? "On" : "Off in this Workspace"}</span>
              <select className="admin-users__toolbar-select" value={row.risk} disabled={saving !== null}
                aria-label={`Risk of ${row.tool}`} data-testid={`mcp-risk-${row.tool}`}
                onChange={(event) => void change(row, event.target.value as McpRisk)}>
                {MCP_RISKS.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
              </select>
            </li>
          ))}
        </ul>
      ) : null}
      {saved ? <p className="sk-hint" role="status" data-testid="mcp-risk-saved">{saved}</p> : null}
      {problem ? <p className="sk-err" role="alert">{problem}</p> : null}
    </section>
  );
}
