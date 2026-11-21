import { useCallback, useEffect, useState } from "react";

import { useAdminNavigation } from "../../adminNavigation";
import { readJson } from "../../utils/adminPanelHelpers";
import { SubTabs } from "../settingsKit/SettingsKit";
import "../settingsKit/settingsKit.css";
import { ApprovalPolicyDrawer } from "./ApprovalPolicyDrawer";
import type { ApprovalPolicy, ToolApprovals, WorkspaceApproval } from "./toolApprovalsModel";
import { RISK_LABEL, readToolApprovals, toolLabel, workspaceApprovalBody, workspaceSummary } from "./toolApprovalsModel";
import { UNATTENDED_WARNING } from "../securityControls/securityControlsModel";

const PATH = "/api/v1/admin/tool-approvals";
type Tab = "approvals" | "mcp";
type Editing = { kind: "default" } | { kind: "workspace"; row: WorkspaceApproval };

const CODE_TEXT: Record<string, string> = {
  tool_approval_risk_unknown: "a risk is not known",
  tool_approval_tool_invalid: "a tool name is not valid",
  tool_approval_mode_invalid: "the mode is not inherit or add",
};

function Chips({ values, tone = "secondary" }: { values: string[]; tone?: string }) {
  return values.length ? (
    <span className="sk-chips">{values.map((value) => <span key={value} className={tone ? `admin-policy-chip admin-policy-chip--${tone}` : "admin-policy-chip"}>{value}</span>)}</span>
  ) : <span className="admin-panel__cell--muted">–</span>;
}

/** The PUT of the platform default or of one Workspace's approvals; the answer is the whole page payload. */
function saveApproval(editing: Editing, mode: "inherit" | "add", policy: ApprovalPolicy) {
  return editing.kind === "default"
    ? readJson<unknown>(`${PATH}/default`, { method: "PUT", body: JSON.stringify(policy) })
    : readJson<unknown>(`${PATH}/workspaces/${encodeURIComponent(editing.row.id)}`, {
      method: "PUT", body: JSON.stringify(workspaceApprovalBody(mode, policy)),
    });
}

// Settings → Security → "Tool & approval policies": which tool calls stop and wait for a person —
// the platform default and each Workspace's additions — plus a read-only overview of the MCP servers each Workspace
// allows (declared in the Workspace's Connectors). Forbidden actions are Policies; who approves is the Approval rule.
export function ToolApprovalsPage() {
  const { openAdminTab } = useAdminNavigation();
  const [data, setData] = useState<ToolApprovals | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("approvals");
  const [editing, setEditing] = useState<Editing | null>(null);
  const [busy, setBusy] = useState(false);
  const [saveProblem, setSaveProblem] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setData(readToolApprovals(await readJson<unknown>(PATH)));
    } catch (error) {
      setProblem((error as { status?: number }).status === 403 ? "Only platform admins can see tool approvals." : "Tool approvals could not be loaded.");
    }
  }, []);
  useEffect(() => { void load(); }, [load]);

  if (problem) return <p className="sk-err" role="alert">{problem}</p>;
  if (!data) return <p className="sk-hint" role="status">Loading tool approvals…</p>;

  const save = async (mode: "inherit" | "add", policy: ApprovalPolicy) => {
    if (!editing) return;
    setBusy(true);
    setSaveProblem(null);
    try {
      setData(readToolApprovals(await saveApproval(editing, mode, policy)));
      setEditing(null);
    } catch (error) {
      const code = (error as { code?: string }).code ?? "";
      setSaveProblem(`Not saved: ${CODE_TEXT[code] ?? "the request was refused"}.`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="sk-page" data-testid="tool-approvals">
      <SubTabs value={tab} onChange={setTab} label="Tool & approval policies"
        tabs={[{ id: "approvals", label: "Approvals" }, { id: "mcp", label: "MCP servers (overview)" }]} />
      {tab === "approvals" ? (
        <ApprovalsTab data={data} onEdit={(next) => { setSaveProblem(null); setEditing(next); }} />
      ) : (
        <McpOverview mcp={data.mcp} onOpenServers={() => openAdminTab("mcp")} />
      )}
      {editing ? (
        <ApprovalPolicyDrawer title={editing.kind === "default" ? "Platform default" : editing.row.name} workspace={editing.kind === "workspace"}
          mode={editing.kind === "default" ? "add" : editing.row.mode} policy={editing.kind === "default" ? data.defaults : editing.row.own}
          defaults={data.defaults} risks={data.risks} tools={data.tools} busy={busy} problem={saveProblem}
          onClose={() => setEditing(null)} onSave={(mode, policy) => void save(mode, policy)} />
      ) : null}
    </div>
  );
}

function ApprovalsTab({ data, onEdit }: { data: ToolApprovals; onEdit: (editing: Editing) => void }) {
  return (
    <div className="sk-page">
      <section className="admin-panel__card" aria-label="Platform default">
        <div className="admin-panel__section-header">
          <span>Platform default</span>
          <button type="button" className="admin-panel__action-btn" data-testid="approval-edit-default"
            onClick={() => onEdit({ kind: "default" })}>Edit</button>
        </div>
        <dl className="work-detail__kv" data-testid="approval-default">
          <dt>Risk</dt><dd><Chips values={data.defaults.require_for_risks.map((risk) => RISK_LABEL[risk] ?? risk)} tone="" /></dd>
          <dt>Always</dt><dd><Chips values={data.defaults.require_for_tools.map(toolLabel)} /></dd>
          <dt>Never</dt><dd><Chips values={data.defaults.exempt_tools.map(toolLabel)} /></dd>
          <dt>Unattended</dt><dd data-testid="approval-default-unattended"><Chips values={data.defaults.unattended_allowed_tools.map(toolLabel)} /></dd>
        </dl>
        {data.defaults.unattended_allowed_tools.length ? <p className="sk-warn" role="note">{UNATTENDED_WARNING}</p> : null}
      </section>
      <table className="admin-panel__table sk-cards" data-testid="approval-workspaces">
        <thead><tr><th>Workspace</th><th>Approvals</th><th>Summary</th><th /></tr></thead>
        <tbody>
          {data.workspaces.length === 0 ? <tr><td colSpan={4} className="admin-panel__cell--muted">No active Workspace.</td></tr> : null}
          {data.workspaces.map((row) => (
            <tr key={row.id}>
              <td data-label="Workspace">{row.name}</td>
              <td data-label="Approvals">
                {row.mode === "inherit" ? <span className="work-badge work-badge--neutral">Inherit</span>
                  : <span className="work-badge work-badge--attention">Adds rules</span>}
              </td>
              <td data-label="Summary">{workspaceSummary(row)}</td>
              <td>
                <button type="button" className="admin-panel__action-btn" data-testid={`approval-edit-${row.id}`}
                  onClick={() => onEdit({ kind: "workspace", row })}>Edit</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function McpOverview({ mcp, onOpenServers }: { mcp: ToolApprovals["mcp"]; onOpenServers: () => void }) {
  return (
    <div className="sk-page">
      {mcp.servers.length === 0 ? (
        <p className="sk-hint">No MCP server is registered.{" "}
          <button type="button" className="sk-link" onClick={onOpenServers}>Open MCP servers</button>
        </p>
      ) : (
        <table className="admin-panel__table sk-cards" data-testid="approval-mcp">
          <thead><tr><th>Workspace</th>{mcp.servers.map((server) => <th key={server}>{server}</th>)}</tr></thead>
          <tbody>
            {mcp.workspaces.map((row) => (
              <tr key={row.id}>
                <td data-label="Workspace">{row.name}</td>
                {mcp.servers.map((server) => (
                  <td key={server} data-label={server}>
                    {row.servers[server] ? <span className="work-badge work-badge--active">On</span> : <span className="work-badge work-badge--neutral">Off</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
