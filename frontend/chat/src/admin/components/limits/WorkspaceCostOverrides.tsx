import { useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";
import {
  REQUEST_COST_CAP,
  SESSION_COST_CAP,
  buildWorkspaceCostCapsPayload,
  costCapInheritFromScope,
} from "../runtimeTab/workspaceCostCapsSave";
import type { CostCapInherit, CostCapKey } from "../runtimeTab/workspaceCostCapsSave";

const SETTINGS = "/admin/chat/api/panel/runtime-settings";
const CAPS: readonly [CostCapKey, string][] = [[SESSION_COST_CAP, "Per session"], [REQUEST_COST_CAP, "Per request"]];

type Settings = {
  agent_session_cost_limit_usd?: number; agent_request_cost_limit_usd?: number;
  cost_limit_scope?: { session_source?: string; request_source?: string };
};

// A Workspace's cost-cap overrides (until the Workspace Models/Budget section owns them): each cap
// is an override or "Inherit platform value"; an empty override is refused, never saved as "no limit".
export function WorkspaceCostOverrides({ workspaces, onSaved }: { workspaces: { id: string; name: string }[]; onSaved: () => void }) {
  const [workspaceId, setWorkspaceId] = useState("");
  const [values, setValues] = useState<Record<CostCapKey, string>>({ [SESSION_COST_CAP]: "", [REQUEST_COST_CAP]: "" });
  const [inherit, setInherit] = useState<CostCapInherit>({ [SESSION_COST_CAP]: true, [REQUEST_COST_CAP]: true });
  const [message, setMessage] = useState<{ error: boolean; text: string } | null>(null);
  const url = (id: string) => `${SETTINGS}?project_id=${encodeURIComponent(id)}`;

  const apply = (settings: Settings) => {
    setInherit(costCapInheritFromScope(settings.cost_limit_scope));
    setValues({
      [SESSION_COST_CAP]: String(settings.agent_session_cost_limit_usd ?? ""),
      [REQUEST_COST_CAP]: String(settings.agent_request_cost_limit_usd ?? ""),
    });
  };

  const choose = async (id: string) => {
    setWorkspaceId(id);
    setMessage(null);
    if (!id) return;
    try {
      apply(await readJson<Settings>(url(id)));
    } catch {
      setMessage({ error: true, text: "The Workspace's caps could not be loaded." });
    }
  };

  const save = async () => {
    const built = buildWorkspaceCostCapsPayload(values, inherit);
    if ("error" in built) {
      setMessage({ error: true, text: built.error });
      return;
    }
    try {
      apply(await readJson<Settings>(url(workspaceId), { method: "PUT", body: JSON.stringify(built.payload) }));
      setMessage({ error: false, text: "Saved: this Workspace's cost caps." });
      onSaved();
    } catch (failure) {
      setMessage({ error: true, text: `Not saved: ${failure instanceof Error ? failure.message : "refused"}.` });
    }
  };

  return (
    <div className="admin-panel__card" data-testid="workspace-cost-overrides">
      <div className="admin-panel__section-header"><span>Workspace cost caps</span></div>
      <label className="admin-panel__field">
        <span>Workspace</span>
        <select value={workspaceId} onChange={(event) => void choose(event.target.value)}>
          <option value="">Choose a Workspace</option>
          {workspaces.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        </select>
      </label>
      {workspaceId ? (
        <div className="admin-panel__form-grid">
          {CAPS.map(([cap, label]) => (
            <div key={cap} className="limits__form">
              <label className="admin-panel__field">
                <span>{label} (USD)</span>
                <input inputMode="decimal" value={inherit[cap] ? "" : values[cap]} disabled={inherit[cap]}
                  onChange={(event) => setValues((current) => ({ ...current, [cap]: event.target.value }))} />
              </label>
              <label className="admin-panel__checkbox">
                <input type="checkbox" checked={inherit[cap]}
                  onChange={(event) => setInherit((current) => ({ ...current, [cap]: event.target.checked }))} />
                Inherit platform value
              </label>
            </div>
          ))}
        </div>
      ) : null}
      {message ? (
        <p className={message.error ? "admin-panel__error" : "admin-panel__success"} role={message.error ? "alert" : "status"}>
          {message.text}
        </p>
      ) : null}
      {workspaceId ? (
        <div className="model-catalog__row-group">
          <button type="button" className="admin-panel__action-btn" onClick={() => void save()}>Save Workspace caps</button>
        </div>
      ) : null}
    </div>
  );
}
