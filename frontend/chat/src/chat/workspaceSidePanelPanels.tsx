import { SegmentedTabs } from "../layout/SegmentedTabs";
import type { WorkspaceChangeEntry } from "../chatWorkspaceTypes";
import { CopyIcon } from "./ChatShellIcons";
import { formatTime } from "./workspaceSidePanelHelpers";
import {
  CleanIcon,
  FolderPlusIcon,
  RefreshIcon,
  SearchIcon,
} from "./workspaceSidePanelIcons";

type WorkspaceTab = "files" | "changes";

export function WorkspaceSidePanelHeader({
  rootPath,
  rootLabel,
  onCopyRootPath,
  onCreateFolder,
  onClean,
  onRefresh,
}: {
  rootPath?: string;
  rootLabel?: string;
  onCopyRootPath: () => void | Promise<void>;
  onCreateFolder: () => void | Promise<void>;
  onClean: () => void | Promise<void>;
  onRefresh: () => void | Promise<void>;
}) {
  const pathLabel = rootPath || rootLabel || "Working Files";
  return (
    <div className="workspace-sidepanel__header">
      <div>
        <div className="workspace-sidepanel__title">Working Files</div>
        <div className="workspace-sidepanel__pathline">
          <span className="workspace-sidepanel__pathtext" title={pathLabel}>
            {pathLabel}
          </span>
          {rootPath ? (
            <button
              type="button"
              className="workspace-sidepanel__pathcopy"
              title="Copy absolute path"
              aria-label="Copy absolute path"
              onClick={() => void onCopyRootPath()}
            >
              <CopyIcon />
            </button>
          ) : null}
        </div>
      </div>
      <div className="workspace-sidepanel__header-actions">
        <button
          type="button"
          className="workspace-sidepanel__icon"
          title="Create folder"
          onClick={() => void onCreateFolder()}
        >
          <FolderPlusIcon />
        </button>
        <button
          type="button"
          className="workspace-sidepanel__icon"
          title="Clean working files"
          onClick={() => void onClean()}
        >
          <CleanIcon />
        </button>
        <button
          type="button"
          className="workspace-sidepanel__icon"
          title="Refresh working files"
          onClick={() => void onRefresh()}
        >
          <RefreshIcon />
        </button>
      </div>
    </div>
  );
}

export function WorkspaceSidePanelControls({
  activeTab,
  onChangeTab,
  bulkMode,
  onToggleBulkMode,
  query,
  onQueryChange,
  fileCount,
  changeCount,
}: {
  activeTab: WorkspaceTab;
  onChangeTab: (next: WorkspaceTab) => void;
  bulkMode: boolean;
  onToggleBulkMode: () => void;
  query: string;
  onQueryChange: (next: string) => void;
  fileCount: number;
  changeCount: number;
}) {
  return (
    <div className="workspace-sidepanel__controls">
      <div className="workspace-sidepanel__topbar">
        <SegmentedTabs label="Workspace files" idPrefix="workspace-sidepanel" size="small" value={activeTab}
          onChange={(key) => onChangeTab(key as WorkspaceTab)}
          tabs={[{ key: "files", label: "Files", count: fileCount }, { key: "changes", label: "Changes", count: changeCount }]} />
        {activeTab === "files" ? (
          <button
            type="button"
            className={`workspace-sidepanel__bulk-toggle ${bulkMode ? "workspace-sidepanel__bulk-toggle--active" : ""}`}
            onClick={onToggleBulkMode}
          >
            Bulk
          </button>
        ) : null}
      </div>

      <label className="workspace-sidepanel__search">
        <SearchIcon />
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          placeholder={
            activeTab === "files" ? "Search files..." : "Search changes..."
          }
        />
      </label>
    </div>
  );
}

export function WorkspaceChangesPanel({
  filteredChanges,
}: {
  filteredChanges: WorkspaceChangeEntry[];
}) {
  if (!filteredChanges.length) {
    return (
      <div className="workspace-sidepanel__changes-body">
        <div className="workspace-sidepanel__empty">
          No working-file changes available yet.
        </div>
      </div>
    );
  }

  return (
    <div className="workspace-sidepanel__changes-body">
      <div className="workspace-sidepanel__list">
        {filteredChanges.map((change) => {
          const statusKey = String(change.status || "").toLowerCase();
          return (
            <div
              key={change.id}
              className={`workspace-sidepanel__change workspace-sidepanel__change--${statusKey}`}
            >
              <span
                className="workspace-sidepanel__change-rail"
                aria-hidden="true"
              />
              <div className="workspace-sidepanel__change-body">
                <div className="workspace-sidepanel__change-top">
                  <span className="workspace-sidepanel__change-tool">
                    {change.toolName || "change"}
                  </span>
                  <span
                    className={`workspace-sidepanel__change-status workspace-sidepanel__change-status--${statusKey}`}
                  >
                    {change.status}
                  </span>
                </div>
                <div className="workspace-sidepanel__change-summary">
                  {change.summary ||
                    change.requestFingerprint ||
                    "No summary available"}
                </div>
                <div className="workspace-sidepanel__change-meta">
                  {change.requestFingerprint ? (
                    <span>{change.requestFingerprint}</span>
                  ) : null}
                  {change.createdAt ? (
                    <span>{formatTime(change.createdAt)}</span>
                  ) : null}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
