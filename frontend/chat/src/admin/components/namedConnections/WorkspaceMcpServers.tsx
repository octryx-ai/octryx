import { useEffect, useState } from "react";
import { useAdminNavigation } from "../../adminNavigation";
import { MCP_ALLOW_API, allowErrorText } from "../mcpAllow/mcpAllowContract";
import { mcpServersListPath } from "../mcpWorkspaceContract";
import { parseMcpServerRows } from "./mcpServerListingModel";
import type { McpServerRow } from "./mcpServerListingModel";
import "./namedConnections.css";

type ReadJson = <T = unknown>(url: string, init?: RequestInit) => Promise<T>;

type Props = {
  projectId: string;
  readJson: ReadJson;
};

// The MCP servers this Workspace can use, next to its connectors' named connections. Registration,
// connection and secrets stay under Admin › Connections › MCP servers; here the Workspace allows a server (runtime WP S6:
// deny-by-default, written into the Workspace's MCP policy). A failed listing shows nothing.
export function WorkspaceMcpServers({ projectId, readJson }: Props) {
  const { openAdminTab } = useAdminNavigation();
  const [rows, setRows] = useState<McpServerRow[] | null>(null);
  const [allowed, setAllowed] = useState<Record<string, boolean>>({});
  const [error, setError] = useState("");
  const allowUrl = `${MCP_ALLOW_API}/workspaces/${encodeURIComponent(projectId)}/mcp-servers`;

  useEffect(() => {
    readJson<{ servers?: { server_id?: string; allowed?: boolean }[] }>(allowUrl)
      .then((body) => setAllowed(Object.fromEntries((body.servers ?? []).map((row) => [String(row.server_id), row.allowed === true]))))
      .catch(() => setAllowed({}));
  }, [allowUrl, readJson]);

  const toggle = async (serverId: string, next: boolean) => {
    setError("");
    try {
      await readJson(`${allowUrl}/${encodeURIComponent(serverId)}`, { method: "PUT", body: JSON.stringify({ allowed: next }) });
      setAllowed((current) => ({ ...current, [serverId]: next }));
    } catch (failure) {
      setError(allowErrorText(failure));
    }
  };

  useEffect(() => {
    let live = true;
    setRows(null);
    readJson(mcpServersListPath(projectId))
      .then((raw) => {
        if (live) setRows(parseMcpServerRows(raw, projectId));
      })
      .catch(() => {
        if (live) setRows(null);
      });
    return () => {
      live = false;
    };
  }, [projectId, readJson]);

  if (rows === null) return null;
  return (
    <section className="admin-panel__stack admin-panel__stack--compact" data-testid="workspace-mcp-servers">
      <div className="admin-panel__section-header">
        <div>
          <span>MCP servers ({rows.length})</span>
          {/* The explanation is in the Workspaces help; here only for assistive technology. */}
          <p className="ds-sr-only">
            MCP servers are registered, connected and bound to secrets under Admin › Connections › MCP servers. A server
            is usable here only after this Workspace allows it.
          </p>
        </div>
        <button type="button" className="admin-panel__action-btn" onClick={() => openAdminTab("mcp")}>
          Manage MCP servers
        </button>
      </div>
      {rows.length === 0 ? (
        <p className="admin-panel__hint">No MCP server is registered for this Workspace or the platform.</p>
      ) : (
        <ul className="named-connections__list">
          {rows.map((row) => (
            <li key={row.key} className="named-connections__row" data-testid="workspace-mcp-server">
              <strong>{row.name}</strong> · {row.scope} · {row.transport} · {row.status}
              {row.key in allowed ? (
                <label className="admin-panel__checkbox">
                  <input type="checkbox" checked={allowed[row.key]} data-testid="workspace-mcp-allow"
                    onChange={(event) => void toggle(row.key, event.target.checked)} />
                  Allowed in this Workspace
                </label>
              ) : null}
            </li>
          ))}
        </ul>
      )}
      {error ? <p className="admin-panel__error" role="alert">{error}</p> : null}
    </section>
  );
}
