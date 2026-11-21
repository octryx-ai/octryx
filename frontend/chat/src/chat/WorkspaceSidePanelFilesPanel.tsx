import type { ToolArtifact } from "../chatThreadTypes";
import type { WorkspaceFileEntry } from "../chatWorkspaceTypes";
import { asArtifact, formatTime, humanSize } from "./workspaceSidePanelHelpers";
import {
  ChevronIcon,
  FileIcon,
  FolderIcon,
  MoveIcon,
  RenameIcon,
  TrashIcon,
} from "./workspaceSidePanelIcons";

type WorkspaceFilesPanelProps = {
  displayedFiles: WorkspaceFileEntry[];
  searchLoading: boolean;
  searchError: string | null;
  loweredQuery: string;
  bulkMode: boolean;
  selectedEntries: WorkspaceFileEntry[];
  selectedPaths: string[];
  selectedPreviewPath: string;
  childrenByParent: Map<string, WorkspaceFileEntry[]>;
  expandedPaths: Record<string, boolean>;
  loadingDirectories: Record<string, boolean>;
  onToggleSelection: (relativePath: string) => void;
  onToggleExpanded: (relativePath: string) => void | Promise<void>;
  onSelectPreviewFile: (entry: WorkspaceFileEntry) => void;
  onOpenArtifact: (artifact: ToolArtifact) => void;
  onRename: () => void | Promise<void>;
  onMove: () => void | Promise<void>;
  onDelete: () => void | Promise<void>;
};

type TreeContext = Pick<
  WorkspaceFilesPanelProps,
  | "bulkMode"
  | "selectedPaths"
  | "selectedPreviewPath"
  | "childrenByParent"
  | "expandedPaths"
  | "loadingDirectories"
  | "onToggleSelection"
  | "onToggleExpanded"
  | "onSelectPreviewFile"
  | "onOpenArtifact"
>;

function entryMeta(entry: WorkspaceFileEntry, isDirectory: boolean, isLoading: boolean, childCount: number) {
  return isDirectory
    ? isLoading
      ? "Loading..."
      : `${childCount} item${childCount === 1 ? "" : "s"}`
    : [
        humanSize(entry.sizeBytes),
        formatTime(entry.modifiedAt || entry.createdAt),
      ]
        .filter(Boolean)
        .join(" · ");
}

function renderEntryButton(ctx: TreeContext, entry: WorkspaceFileEntry, isDirectory: boolean, meta: string) {
  const { onToggleExpanded, onSelectPreviewFile, onOpenArtifact } = ctx;
  return (
  <button
    type="button"
    className="workspace-sidepanel__tree-entry"
    onClick={() => {
      if (isDirectory) {
        void onToggleExpanded(entry.relativePath);
        return;
      }
      if (entry.url) {
        onSelectPreviewFile(entry);
      }
    }}
    onDoubleClick={() => {
      if (!isDirectory && entry.url) {
        onOpenArtifact(asArtifact(entry));
      }
    }}
  >
    <span className="workspace-sidepanel__tree-icon">
      {isDirectory ? <FolderIcon /> : <FileIcon />}
    </span>
    <span className="workspace-sidepanel__tree-copy">
      <span className="workspace-sidepanel__tree-name">
        {entry.name}
      </span>
      {meta ? (
        <span className="workspace-sidepanel__tree-meta">{meta}</span>
      ) : null}
    </span>
  </button>
  );
}

function renderTreeEntry(ctx: TreeContext, entry: WorkspaceFileEntry) {
  const { bulkMode, selectedPaths, selectedPreviewPath, childrenByParent, expandedPaths, loadingDirectories } = ctx;
  const { onToggleSelection, onToggleExpanded } = ctx;
  const childEntries = childrenByParent.get(entry.relativePath) ?? [];
  const isDirectory = entry.kind === "directory";
  const isOpen = expandedPaths[entry.relativePath] ?? true;
  const isSelected = selectedPaths.includes(entry.relativePath);
  const isPreviewActive = selectedPreviewPath === entry.relativePath;
  const isLoading = Boolean(loadingDirectories[entry.relativePath]);
  const childCount = entry.childCount ?? childEntries.length;
  const meta = entryMeta(entry, isDirectory, isLoading, childCount);

  return (
    <div key={entry.path} className="workspace-sidepanel__tree-node-shell">
      <div
        className={`workspace-sidepanel__tree-row ${isSelected ? "workspace-sidepanel__tree-row--selected" : ""} ${isPreviewActive ? "workspace-sidepanel__tree-row--preview-active" : ""}`}
        style={{ paddingLeft: `${0.65 + (entry.depth ?? 0) * 0.95}rem` }}
        title={entry.path}
      >
        <button
          type="button"
          className="workspace-sidepanel__tree-toggle"
          onClick={() => {
            if (isDirectory) {
              void onToggleExpanded(entry.relativePath);
            }
          }}
          aria-label={isOpen ? "Collapse folder" : "Expand folder"}
        >
          {isDirectory ? <ChevronIcon open={isOpen} /> : <span />}
        </button>
        {bulkMode ? (
          <label className="workspace-sidepanel__tree-check">
            <input
              type="checkbox"
              checked={isSelected}
              onChange={() => onToggleSelection(entry.relativePath)}
            />
          </label>
        ) : (
          <span className="workspace-sidepanel__tree-check workspace-sidepanel__tree-check--spacer" />
        )}
          {renderEntryButton(ctx, entry, isDirectory, meta)}
      </div>
          {isDirectory && isOpen ? renderTree(ctx, entry.relativePath) : null}
    </div>
  );
}

function renderTree(ctx: TreeContext, parentPath = "") {
  const entries = ctx.childrenByParent.get(parentPath) ?? [];
  return entries.map((entry) => renderTreeEntry(ctx, entry));
}

function FilesBulkBar({
  selectedEntries,
  onRename,
  onMove,
  onDelete,
}: Pick<WorkspaceFilesPanelProps, "selectedEntries" | "onRename" | "onMove" | "onDelete">) {
  return (
    <div className="workspace-sidepanel__bulkbar">
      <span>
        {selectedEntries.length
          ? `${selectedEntries.length} selected`
          : "Select files"}
      </span>
      <div className="workspace-sidepanel__bulk-actions">
        <button
          type="button"
          className="workspace-sidepanel__bulk-btn"
          disabled={selectedEntries.length !== 1}
          onClick={() => void onRename()}
        >
          <RenameIcon />
          <span>Rename</span>
        </button>
        <button
          type="button"
          className="workspace-sidepanel__bulk-btn"
          disabled={!selectedEntries.length}
          onClick={() => void onMove()}
        >
          <MoveIcon />
          <span>Move</span>
        </button>
        <button
          type="button"
          className="workspace-sidepanel__bulk-btn workspace-sidepanel__bulk-btn--danger"
          disabled={!selectedEntries.length}
          onClick={() => void onDelete()}
        >
          <TrashIcon />
          <span>Delete</span>
        </button>
      </div>
    </div>
  );
}

export function WorkspaceFilesPanel(props: WorkspaceFilesPanelProps) {
  const { displayedFiles, searchLoading, searchError, loweredQuery, bulkMode } = props;
  if (searchLoading) {
    return (
      <div className="workspace-sidepanel__navigator-body">
        <div className="workspace-sidepanel__empty">
          Searching working files...
        </div>
      </div>
    );
  }
  if (searchError) {
    return (
      <div className="workspace-sidepanel__navigator-body">
        <div className="workspace-sidepanel__empty">{searchError}</div>
      </div>
    );
  }
  if (!displayedFiles.length) {
    return (
      <div className="workspace-sidepanel__navigator-body">
        <div className="workspace-sidepanel__empty">
          {loweredQuery
            ? "No working files match the current filter."
            : "No working files are available yet."}
        </div>
      </div>
    );
  }

  return (
    <div className="workspace-sidepanel__navigator-body">
      {bulkMode ? (
        <FilesBulkBar
          selectedEntries={props.selectedEntries}
          onRename={props.onRename}
          onMove={props.onMove}
          onDelete={props.onDelete}
        />
      ) : null}
      <div className="workspace-sidepanel__tree">{renderTree(props)}</div>
    </div>
  );
}
