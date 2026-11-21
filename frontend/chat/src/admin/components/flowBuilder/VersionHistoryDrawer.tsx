import type { FlowDefinitionVersion } from "./flowBuilderTypes";
import { formatDate } from "../../utils/dateTime";

type VersionHistoryDrawerProps = {
  versions: FlowDefinitionVersion[];
  onClose: () => void;
  onRestore: (version: FlowDefinitionVersion) => void;
  busy: boolean;
};

export function VersionHistoryDrawer({
  versions,
  onClose,
  onRestore,
  busy,
}: VersionHistoryDrawerProps) {
  return (
    <div className="version-history-drawer">
      <div className="version-history-drawer__header">
        <span className="version-history-drawer__title">Version History</span>
        <button type="button" onClick={onClose}>
          ✕
        </button>
      </div>

      <div className="version-history-drawer__list">
        {versions.length === 0 ? (
          <p className="admin-panel__muted">No published versions yet.</p>
        ) : (
          versions.map((version) => (
            <div
              key={version.id}
              className={`version-history-drawer__item ${
                version.status === "published"
                  ? "version-history-drawer__item--published"
                  : ""
              }`}
            >
              <div className="version-history-drawer__item-meta">
                <span className="version-history-drawer__item-version">
                  v{version.version}
                </span>
                <span className="version-history-drawer__item-status">
                  {version.status}
                </span>
                <span className="version-history-drawer__item-date">
                  {version.created_at
                    ? formatDate(version.created_at)
                    : "—"}
                </span>
              </div>
              <div className="version-history-drawer__item-actions">
                <button
                  type="button"
                  onClick={() => onRestore(version)}
                  disabled={busy}
                >
                  Restore
                </button>
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
