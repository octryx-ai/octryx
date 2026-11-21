import { useEffect, useState } from "react";

import { loadSkillWorkspaces } from "./skillCatalogApi";
import { SURFACES, SURFACE_LABELS } from "./skillCatalogTypes";
import { assignedByLabel, reasonLabel, readinessBadge, refusalText } from "./skillCatalogModel";
import type { Extension } from "./skillCatalogTypes";
import type { WorkspaceReach } from "./skillDeliveryTypes";
import { reachSummary } from "./skillDetailModel";

// Detail → Workspaces (mock `renderDetail` workspaces): every Workspace with what each surface receives (delivered or
// the reason it does not), how it is assigned, and the readiness with the policy refusals behind it. Assigning happens
// on the Workspace page.
export function SkillWorkspacesTab({ skillId, kind, labels, extension, onOpenWorkspaces }: {
  skillId: string;
  kind: string;
  labels: Record<string, string>;
  extension: Extension | undefined;
  onOpenWorkspaces: () => void;
}) {
  const [rows, setRows] = useState<WorkspaceReach[] | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const mcp = kind === "mcp_server";

  useEffect(() => {
    let alive = true;
    loadSkillWorkspaces(skillId)
      .then((raw) => { if (alive) setRows(((raw as { workspaces?: WorkspaceReach[] }).workspaces) ?? []); })
      .catch((error: unknown) => { if (alive) setProblem(refusalText(error)); });
    return () => { alive = false; };
  }, [skillId]);

  if (problem) return <p className="policies__warn" role="alert">{problem}</p>;
  if (!rows) return <p className="admin-panel__hint" role="status">Loading Workspaces…</p>;
  const tools = extension?.tools;
  const toolText = (surface: "platform_chat" | "octryx_claude") => {
    const required = tools?.[surface]?.required ?? [];
    if (!required.length) return "none (instructions only)";
    return required.map((tool, index) => <span key={tool}>{index ? ", " : ""}<span className="admin-policy-inline-code">{tool}</span></span>);
  };
  return (
    <div data-testid="skill-workspaces">
      <div className="skills__scroll">
        <table className="admin-panel__table">
          <thead><tr><th scope="col">Workspace</th>{SURFACES.map((surface) => <th key={surface} scope="col">{SURFACE_LABELS[surface]}</th>)}<th scope="col">Assigned by</th><th scope="col">Readiness</th></tr></thead>
          <tbody>
            {rows.map((row) => {
              const summary = reachSummary(row);
              const badge = summary.delivered ? readinessBadge(summary.readiness) : { label: "Not delivered", className: "work-badge work-badge--neutral" };
              return (
                <tr key={row.project_id} className={summary.delivered ? undefined : "admin-panel__row--inactive"} data-testid="skill-workspace-row">
                  <td>{row.name}</td>
                  {SURFACES.map((surface) => {
                    const entry = row.surfaces[surface];
                    return (
                      <td key={surface}>
                        {entry?.delivered ? <span className="work-badge work-badge--active">Delivered</span>
                          : <span className="admin-panel__cell--muted">{entry ? reasonLabel(entry.reason) : "—"}</span>}
                      </td>
                    );
                  })}
                  <td>{summary.assignedBy ? assignedByLabel(summary.assignedBy, labels) : "—"}</td>
                  <td>
                    <span className={badge.className}>{badge.label}</span>
                    {(summary.readiness?.refusals ?? []).map((refusal, index) => (
                      <div key={`${refusal.tool}-${index}`} className="policies__sub">
                        <span className="admin-policy-inline-code">{refusal.tool}</span> refused by {refusal.policy}
                        {refusal.rule ? <> (<span className="admin-policy-inline-code">{refusal.rule}</span>)</> : null}
                        {refusal.reason ? `: ${refusal.reason}` : ""}
                      </div>
                    ))}
                  </td>
                </tr>
              );
            })}
            {rows.length ? null : <tr><td colSpan={SURFACES.length + 3}><div className="admin-panel__empty-state">No Workspace exists yet.</div></td></tr>}
          </tbody>
        </table>
      </div>
      <p className="skills__hint skill-detail__gap">
        {mcp ? "Assigning an MCP server entry never changes the MCP policy. The Workspace MCP policy (deny-by-default) stays the only switch that lets the server start."
          : <>Required tools (declared in the catalog): octryx-claude {toolText("octryx_claude")}; platform chat: {toolText("platform_chat")}.
            Every tool call is still checked by the Workspace tool policy and the platform policies.</>}
      </p>
      <button type="button" className="admin-panel__action-btn" data-testid="skill-workspaces-assign" onClick={onOpenWorkspaces}>Assign in Workspaces</button>
    </div>
  );
}
