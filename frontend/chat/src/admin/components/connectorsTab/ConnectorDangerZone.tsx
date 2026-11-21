import { useState, type ReactNode } from "react";

import { ConfirmDialog } from "../confirm/ConfirmDialog";
import type { ActionMenuItem } from "../workflowSurfaces/ActionMenu";

type Usage = { workspaces: string[]; named_connections: string[]; knowledge_sources: number; references: number };

type ConnectorRef = { tool_name: string; label: string; is_active: boolean; configured: boolean };

// Pause/Resume and a guarded Remove of a configured connector. Remove lists what
// uses the connector and stays disabled until nothing does; the name must be typed to confirm.
// The connector's side panel shows Pause/Resume as its footer action and Remove… in its ⋯ menu.
export function useConnectorLifecycle(connector: ConnectorRef, ctx: Record<string, unknown>): {
  toggle: ReactNode;
  menuItems: ActionMenuItem[];
  dialog: ReactNode;
} {
  const { handleDeleteConnector, handleSetConnectorActive, readJson } = ctx as Record<string, any>;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [removing, setRemoving] = useState(false);

  if (!connector.configured) return { toggle: null, menuItems: [], dialog: null };

  const togglePause = async () => {
    setBusy(true);
    setError(null);
    try {
      await handleSetConnectorActive(connector.tool_name, !connector.is_active);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not change the connector.");
    } finally {
      setBusy(false);
    }
  };

  const openRemove = async () => {
    setError(null);
    setUsage(null);
    setRemoving(true);
    try {
      setUsage(await readJson(`/admin/chat/api/panel/connectors/${connector.tool_name}/usage`));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not check where the connector is used.");
    }
  };

  const remove = async (typed: string) => {
    setBusy(true);
    setError(null);
    try {
      await handleDeleteConnector(connector.tool_name, typed);
      setRemoving(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Not removed.");
    } finally {
      setBusy(false);
    }
  };

  const inUse = Boolean(usage && usage.references > 0);

  const toggle = (
    <>
      {error && !removing ? <span className="automation-tone--error" role="alert">{error}</span> : null}
      <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => void togglePause()}
        data-testid="connector-toggle">
        {connector.is_active ? "Pause" : "Resume"}
      </button>
    </>
  );
  const dialog = removing ? (
    <ConfirmDialog
      title={`Remove ${connector.label}?`}
      confirmLabel="Remove connector"
      typeToConfirm={inUse || !usage ? undefined : connector.label}
      confirmDisabled={!usage || inUse}
      busy={busy}
      error={error}
      onCancel={() => setRemoving(false)}
      onConfirm={(typed) => void remove(typed)}
    >
      {!usage ? (
        <p>Checking where it is used…</p>
      ) : inUse ? (
        <>
          <p>It is still used. Reassign or remove these first:</p>
          <ul>
            {usage.workspaces.length ? <li>Workspaces: {usage.workspaces.join(", ")}</li> : null}
            {usage.named_connections.length ? <li>Named connections: {usage.named_connections.join(", ")}</li> : null}
            {usage.knowledge_sources ? <li>{usage.knowledge_sources} knowledge source{usage.knowledge_sources === 1 ? "" : "s"}</li> : null}
          </ul>
        </>
      ) : (
        <p>The stored sign-in is deleted and agents lose its tools. Pause keeps everything instead.</p>
      )}
    </ConfirmDialog>
  ) : null;
  return {
    toggle,
    menuItems: [{ label: "Remove…", danger: true, disabled: busy, onSelect: () => void openRemove(), testId: "connector-remove" }],
    dialog,
  };
}
