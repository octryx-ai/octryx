import { useEffect, useState, type Dispatch, type SetStateAction } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import { SettingsDrawer } from "../projectsTab/SettingsDrawer";
import "./mcpAllow.css";
import { MCP_ALLOW_API, allowBody, allowErrorText, initialTools, readAllow } from "./mcpAllowContract";
import type { ServerAllow } from "./mcpAllowContract";

type Props = { serverId: string; serverName: string; onClose: () => void; onSaved: () => void };

const toggle = (list: string[], item: string, on: boolean) => (on ? [...list, item] : list.filter((entry) => entry !== item));

// The PUT of the ticked Workspaces and tools; a choice the body refuses is shown instead of being sent.
async function saveAllow(url: string, built: ReturnType<typeof allowBody>, steps: {
  setError: (error: string) => void;
  setSaving: (saving: boolean) => void;
  onSaved: () => void;
}) {
  if (!built.body) {
    steps.setError(built.error ?? "");
    return;
  }
  steps.setSaving(true);
  try {
    await readJson<unknown>(url, { method: "PUT", body: JSON.stringify(built.body) });
    steps.onSaved();
  } catch (failure) {
    steps.setError(allowErrorText(failure));
  } finally {
    steps.setSaving(false);
  }
}

// Runtime → MCP servers → "Allow in Workspaces": which Workspaces may use the server and which of
// its tools they see. Saved into each Workspace's MCP policy; the Workspace's Connectors section shows the same.
export function McpAllowDrawer({ serverId, serverName, onClose, onSaved }: Props) {
  const [allow, setAllow] = useState<ServerAllow | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [allTools, setAllTools] = useState(true);
  const [tools, setTools] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const url = `${MCP_ALLOW_API}/mcp-servers/${encodeURIComponent(serverId)}/allow`;

  useEffect(() => {
    readJson<unknown>(url)
      .then((payload) => {
        const read = readAllow(payload);
        setAllow(read);
        setSelected(read.workspaces.filter((row) => row.allowed).map((row) => row.workspaceId));
        const start = initialTools(read);
        setAllTools(start.allTools);
        setTools(start.tools);
      })
      .catch(() => setError("The Workspaces could not be loaded."));
  }, [url]);

  const save = () => saveAllow(url, allowBody(selected, allTools, tools), { setError, setSaving, onSaved });

  return (
    <SettingsDrawer
      eyebrow="MCP server"
      title={`Allow ${serverName} in Workspaces`}
      size="detail"
      onClose={onClose}
      footer={
        <>
          <button type="button" className="admin-panel__action-btn" onClick={onClose}>Cancel</button>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={saving || !allow}
            data-testid="mcp-allow-save" onClick={() => void save()}>
            {saving ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <p className="admin-panel__hint">Saved in each Workspace's Connectors section. You can also allow it from there.</p>
      {allow ? (
        <AllowChoices allow={allow} selected={selected} setSelected={setSelected} allTools={allTools} setAllTools={setAllTools}
          tools={tools} setTools={setTools} />
      ) : null}
      {error ? <p className="admin-panel__error" role="alert">{error}</p> : null}
    </SettingsDrawer>
  );
}

type ListSetter = Dispatch<SetStateAction<string[]>>;

// The Workspaces that may use the server, and all tools or the ticked ones.
function AllowChoices({ allow, selected, setSelected, allTools, setAllTools, tools, setTools }: {
  allow: ServerAllow;
  selected: string[];
  setSelected: ListSetter;
  allTools: boolean;
  setAllTools: (all: boolean) => void;
  tools: string[];
  setTools: ListSetter;
}) {
  return (
    <>
      <div className="work-detail__section">
        <h3>Workspaces</h3>
        {allow.workspaces.map((row) => (
          <label key={row.workspaceId} className="admin-panel__checkbox">
            <input type="checkbox" checked={selected.includes(row.workspaceId)}
              onChange={(event) => setSelected((current) => toggle(current, row.workspaceId, event.target.checked))} />
            {row.name}
          </label>
        ))}
      </div>
      <div className="work-detail__section">
        <h3>Tools exposed</h3>
        <div className="mcp-allow__choices" role="radiogroup" aria-label="Tools exposed">
          <label className="admin-option-card">
            <input type="radio" name="mcp-tools" checked={allTools} onChange={() => setAllTools(true)} />
            <span className="admin-option-card__body">
              <span className="admin-option-card__title">All tools</span>
              <span className="admin-option-card__desc">Including ones the server adds later.</span>
            </span>
          </label>
          <label className="admin-option-card">
            <input type="radio" name="mcp-tools" checked={!allTools} onChange={() => setAllTools(false)}
              disabled={!allow.tools.length} />
            <span className="admin-option-card__body">
              <span className="admin-option-card__title">Selected tools</span>
              <span className="admin-option-card__desc">
                {allow.tools.length ? "Only the tools ticked below." : "Connect the server to list its tools."}
              </span>
            </span>
          </label>
        </div>
        {!allTools ? allow.tools.map((tool) => (
          <label key={tool} className="admin-panel__checkbox">
            <input type="checkbox" checked={tools.includes(tool)}
              onChange={(event) => setTools((current) => toggle(current, tool, event.target.checked))} />
            {tool}
          </label>
        )) : null}
        <p className="model-catalog__sub">Approval and policy rules still apply per tool (Settings → Security, Governance).</p>
      </div>
    </>
  );
}
