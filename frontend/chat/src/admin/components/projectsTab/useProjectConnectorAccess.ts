// Workspace connector access state: the listing with one draft per connector, the open panel, saving and the
// named connections available in the Workspace.
import { useCallback, useEffect, useState } from "react";

import { listConnections } from "../connections/connectionsApi";
import type { AdminProjectQuality } from "../../types/projectQualityTypes";
import type { AvailableConnection } from "./workspaceConnectorTableState";
import { buildLimits, draftFromAccess, EMPTY_DRAFT } from "./ProjectConnectorSettingsHelpers";
import type {
  ConnectorDraft,
  ProjectConnectorAccess,
  ProjectConnectorAccessResponse,
} from "./ProjectConnectorSettingsHelpers";

type ReadJson = <T = unknown>(url: string, init?: RequestInit) => Promise<T>;

export function useConnectorAccessState() {
  const [connectors, setConnectors] = useState<ProjectConnectorAccess[]>([]);
  const [drafts, setDrafts] = useState<Record<string, ConnectorDraft>>({});
  const [saving, setSaving] = useState<string | null>(null);
  const [saved, setSaved] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);
  const [openName, setOpenName] = useState<string | null>(null);
  // A refused access save (422 {code: connector_access_invalid, message}) is shown in its panel.
  const [accessError, setAccessError] = useState<{
    connector: string;
    text: string;
  } | null>(null);
  // Connectors whose Workspace-own connection can serve runtime access without the global one.
  const [ownReady, setOwnReady] = useState<Record<string, boolean>>({});
  return {
    connectors, setConnectors, drafts, setDrafts, saving, setSaving, saved, setSaved, error, setError, loaded, setLoaded,
    openName, setOpenName, accessError, setAccessError, ownReady, setOwnReady,
  };
}

export type ConnectorAccessState = ReturnType<typeof useConnectorAccessState>;

// The named connections available here (Admin › Connections): a connector row says when one of them serves it.
export function useAvailableConnections(projectId: string | undefined) {
  const [available, setAvailable] = useState<AvailableConnection[]>([]);
  useEffect(() => {
    let current = true;
    if (projectId) {
      void listConnections(projectId).then((result) => {
        if (current && result.kind === "ok") {
          setAvailable(result.connections.map((row) => ({ type: row.type, name: row.name, state: row.state })));
        }
      });
    }
    return () => { current = false; };
  }, [projectId]);
  return available;
}

type ListingSetters = Pick<ConnectorAccessState, "setConnectors" | "setDrafts">;

function applyListing(state: ListingSetters, list: ProjectConnectorAccess[]) {
  state.setConnectors(list);
  state.setDrafts(Object.fromEntries(list.map((item) => [item.connector_name, draftFromAccess(item)])));
}

export function useConnectorAccessLoad(state: ConnectorAccessState, project: AdminProjectQuality | null, readJson: ReadJson) {
  const { setOwnReady, setError, setLoaded, setConnectors, setDrafts } = state;
  const markOwnReady = useCallback((connectorName: string, ready: boolean) => {
    setOwnReady((current) => (current[connectorName] === ready ? current : { ...current, [connectorName]: ready }));
  }, [setOwnReady]);

  const loadConnectors = useCallback(async () => {
    if (!project?.id || !readJson) return;
    setError(null);
    try {
      const data = await readJson<ProjectConnectorAccessResponse>(
        `/admin/chat/api/panel/projects/${project.id}/connectors`,
      );
      applyListing({ setConnectors, setDrafts }, data.connectors || []);
      setLoaded(true);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load connector access",
      );
    }
  }, [project?.id, readJson, setError, setLoaded, setConnectors, setDrafts]);

  useEffect(() => {
    void loadConnectors();
  }, [loadConnectors]);
  return markOwnReady;
}

/** The access actions of the connector panel: edit a draft, save it, or drop it on close. */
export function connectorAccessActions(state: ConnectorAccessState, project: AdminProjectQuality | null, readJson: ReadJson) {
  const updateDraft = (connectorName: string, patch: Partial<ConnectorDraft>) => {
    state.setDrafts((current) => ({
      ...current,
      [connectorName]: { ...(current[connectorName] || EMPTY_DRAFT), ...patch },
    }));
    state.setSaved(null);
  };

  const handleSave = async (connector: ProjectConnectorAccess) => {
    if (!project?.id || !readJson) return;
    const draft = state.drafts[connector.connector_name] || EMPTY_DRAFT;
    state.setSaving(connector.connector_name);
    state.setSaved(null);
    state.setError(null);
    state.setAccessError(null);
    try {
      const data = await readJson<ProjectConnectorAccessResponse>(
        `/admin/chat/api/panel/projects/${project.id}/connectors/${connector.connector_name}`,
        { method: "PUT", body: JSON.stringify({ is_active: draft.enabled, limits: buildLimits(draft, connector.limit_fields || []) }) },
      );
      applyListing(state, data.connectors || []);
      state.setSaved(connector.connector_name);
      window.setTimeout(() => state.setSaved(null), 3000);
    } catch (err) {
      state.setAccessError({
        connector: connector.connector_name,
        text: `Access not saved: ${err instanceof Error && err.message ? err.message : "the request failed"}`,
      });
    } finally {
      state.setSaving(null);
    }
  };

  // Cancel, ✕ and Escape drop the unsaved changes of the open connector.
  const closePanel = () => {
    const open = state.connectors.find((item) => item.connector_name === state.openName);
    if (open) state.setDrafts((current) => ({ ...current, [open.connector_name]: draftFromAccess(open) }));
    state.setAccessError(null);
    state.setSaved(null);
    state.setOpenName(null);
  };
  return { updateDraft, handleSave, closePanel };
}
