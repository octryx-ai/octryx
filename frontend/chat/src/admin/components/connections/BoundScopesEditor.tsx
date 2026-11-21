import { useEffect, useState } from "react";

import { workspaceSectionHref } from "../projectsTab/workspaceSettingsLink";
import { Field, type FieldErrors } from "./ConnectionFields";
import { boundHint, boundKeysProblem, parseBoundKeys, perWorkspaceLine, unboundTodayText, type UnboundToday } from "./boundScopes";
import { loadUnboundToday } from "./connectionsApi";
import type { Binding } from "./connectionTypes";
import type { WorkspaceRef } from "./connectionsModel";

// "Spaces / Projects this connection serves" (bound_scopes) on the connection Overview, for types that bind keys.
// Platform admins edit it; everyone else reads it. While the connection binds nothing, the section says what applies
// today: each Workspace's allowed list (or the global one), read from the Workspace connector settings, with links
// to where it is set (boundScopes.ts has the rules).

type Props = {
  binding: Binding; value: string; saved: string[]; editable: boolean; errors: FieldErrors; isAdmin: boolean;
  // The Workspaces the connection is available in (all of them for "All workspaces").
  workspaces: WorkspaceRef[]; type: string;
  onChange: (text: string) => void; onOpenConnectorSettings?: (type: string) => void;
  // Reports what applies today while unbound (the save confirmation names what binding leaves out).
  onToday?: (today: UnboundToday | null) => void;
};

export function BoundScopesEditor({
  binding, value, saved, editable, errors, isAdmin, workspaces, type, onChange, onOpenConnectorSettings, onToday,
}: Props) {
  const [today, setToday] = useState<UnboundToday | null | undefined>(undefined);
  const unbound = saved.length === 0;
  const workspaceKey = workspaces.map((ref) => ref.id).join(",");
  useEffect(() => {
    onToday?.(null);
    if (!unbound || !isAdmin) {
      setToday(null);
      return;
    }
    let current = true;
    setToday(undefined);
    void loadUnboundToday(workspaces, type, binding.allowlistField).then((next) => {
      if (!current) return;
      setToday(next);
      onToday?.(next);
    });
    return () => { current = false; };
    // workspaceKey stands for the Workspaces; onToday is a setter.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [unbound, isAdmin, workspaceKey, type, binding.allowlistField]);

  const label = `${binding.plural} this connection serves`;
  const problem = editable ? boundKeysProblem(parseBoundKeys(value, binding), binding) : "";
  return (
    <div className="connections__bound" data-testid="connection-bound-scopes">
      {editable ? (
        <Field label={label} path="bound_scopes" errors={errors}>
          <input className="admin-panel__input connections__mono" value={value} placeholder={binding.example ? `e.g. ${binding.example}` : ""}
            onChange={(event) => onChange(event.target.value)} data-testid="connection-bound-scopes-input" />
          {problem ? <span className="connections__field-error" role="alert" data-testid="connection-bound-scopes-problem">{problem}</span> : null}
        </Field>
      ) : (
        <p className="connections__fact" data-testid="connection-bound-scopes-read">
          {label}: {saved.length ? <span className="connections__mono">{saved.join(", ")}</span> : "none (not bound)"}
        </p>
      )}
      <p className="connections__hint">{boundHint(binding)}</p>
      {unbound ? (
        <div className="connections__hint" data-testid="connection-unbound-today">
          {today ? <p className="connections__mono-list" data-testid="connection-unbound-today-list">{unboundTodayText(today, binding)}</p> : null}
          {today === undefined && isAdmin ? <p>Reading the Workspaces' allowed {binding.plural.toLowerCase()}…</p> : null}
          <p>
            {today ? perWorkspaceLine(binding) : `Each Workspace's allowed ${binding.plural.toLowerCase()} apply (Workspace settings › Connector settings).`}
            {" "}
            {workspaces.slice(0, 6).map((ref, index) => (
              <span key={ref.id}>{index ? " · " : ""}<a href={workspaceSectionHref(ref.id, "connectors")}
                data-testid={`connection-allowlist-link-${ref.id}`}>{ref.name}</a></span>
            ))}
            {workspaces.length > 6 ? " · …" : null}
            {onOpenConnectorSettings ? (
              <>{workspaces.length ? " · " : ""}<button type="button" className="ds-link-button" onClick={() => onOpenConnectorSettings(type)}
                data-testid="connection-allowlist-global">Global connector settings</button></>
            ) : null}
          </p>
        </div>
      ) : null}
    </div>
  );
}
