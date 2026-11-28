import { KIND_LABEL } from "../connectorDisplay";
import type { SourceConnector } from "../connectorTypes";
import { isLocalSnapshot } from "../gitRepositoryScope";
import type { ActionMenuItem } from "../../workflowSurfaces/ActionMenu";

const CONFIGURABLE_KINDS = new Set(Object.keys(KIND_LABEL));

export type SourceActions = {
  onRun: (connector: SourceConnector) => void;
  onShow: (connector: SourceConnector) => void;
  onEdit: (connector: SourceConnector) => void;
  onToggle: (connector: SourceConnector) => void;
  onReleases: (connector: SourceConnector) => void;
  onDelete: (connector: SourceConnector) => void;
  onOpenUploads: () => void;
};

export function sourceMenuItems(connector: SourceConnector, { busy, running }: { busy: boolean; running: boolean },
  actions: SourceActions): ActionMenuItem[] {
  const paused = connector.state === "paused";
  // A local snapshot is created and fed by the launcher: read-only here, no edit and no sync.
  const snapshot = isLocalSnapshot(connector);
  const configurable = !snapshot && CONFIGURABLE_KINDS.has(connector.kind);
  const syncing = connector.running || running;
  return [
    ...(snapshot ? [] : [{ label: syncing ? "Syncing…" : "Sync now", onSelect: () => actions.onRun(connector), disabled: busy || paused || syncing }]),
    ...(configurable ? [
      { label: paused ? "Resume" : "Pause", onSelect: () => actions.onToggle(connector), disabled: busy },
      { label: "Edit", onSelect: () => actions.onEdit(connector), disabled: busy },
      ...(connector.kind === "jira" ? [{ label: "Releases", onSelect: () => actions.onReleases(connector), disabled: busy }] : []),
    ] : []),
    { label: syncing ? "Remove (wait until the sync finishes)" : "Remove", onSelect: () => actions.onDelete(connector),
      danger: true, disabled: busy || syncing },
  ];
}

export function sourcePageHref(workspaceId: string, connectorKey: string): string {
  const params = new URLSearchParams({ area: "knowledge", tab: "workspaceKnowledge", workspace_id: workspaceId, source: connectorKey, source_view: "page" });
  return `/chat?${params.toString()}`;
}

