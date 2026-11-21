import type { ToolArtifact } from "../chatThreadTypes";
import type { WorkspaceFileEntry } from "../chatWorkspaceTypes";
import { ArtifactPreviewBody } from "./artifactPreviewBody";
import { artifactDownloadUrl, artifactOpenUrl, humanFileSize } from "./artifactPreviewUtils";
import { classifyArtifact, previewCopy } from "./artifactPreviewKind";
import { WorkspaceSidePanelPreviewTabs } from "./WorkspaceSidePanelPreviewTabs";
import { asArtifact, formatTime } from "./workspaceSidePanelHelpers";

function WorkspacePreviewExpandIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M11.25 4.75h4v4" />
      <path d="M15.25 4.75 9.75 10.25" />
      <path d="M8.75 5.25H6A1.25 1.25 0 0 0 4.75 6.5v7A1.25 1.25 0 0 0 6 14.75h7A1.25 1.25 0 0 0 14.25 13.5v-2.75" />
    </svg>
  );
}

function WorkspacePreviewDownloadIcon() {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d="M10 4.5v7" />
      <path d="m7.25 8.75 2.75 2.75 2.75-2.75" />
      <path d="M5 14.5h10" />
    </svg>
  );
}

function WorkspacePreviewEmptyState() {
  return (
    <div className="workspace-sidepanel__preview-empty">
      <div className="workspace-sidepanel__preview-empty-title">
        Select a file to preview it here
      </div>
      <div className="workspace-sidepanel__preview-empty-copy">
        The workspace pane can stay open as a live file navigator and inline
        preview surface.
      </div>
    </div>
  );
}

function WorkspacePreviewHeader({
  artifact,
  entry,
  onOpenArtifact,
}: {
  artifact: ToolArtifact;
  entry: WorkspaceFileEntry;
  onOpenArtifact: (artifact: ToolArtifact) => void;
}) {
  const kind = classifyArtifact(artifact);
  const copy = previewCopy(kind);

  return (
    <div className="workspace-sidepanel__preview-header">
      <div className="workspace-sidepanel__preview-identity">
        <div className="workspace-sidepanel__preview-eyebrow">
          {copy.eyebrow}
        </div>
        <div
          className="workspace-sidepanel__preview-name"
          title={entry.relativePath || entry.path}
        >
          {entry.name}
        </div>
        <div className="workspace-sidepanel__preview-meta">
          <span>{kind}</span>
          <span>{artifact.mediaType || "unknown"}</span>
          {artifact.sizeBytes ? (
            <span>{humanFileSize(artifact.sizeBytes)}</span>
          ) : null}
          {entry.modifiedAt || entry.createdAt ? (
            <span>{formatTime(entry.modifiedAt || entry.createdAt)}</span>
          ) : null}
        </div>
        <div
          className="workspace-sidepanel__preview-path"
          title={entry.relativePath || entry.path}
        >
          {entry.relativePath || entry.path}
        </div>
      </div>
      <div
        className="workspace-sidepanel__preview-actions"
        role="toolbar"
        aria-label="Preview actions"
      >
        <button
          type="button"
          className="workspace-sidepanel__preview-action workspace-sidepanel__preview-action--primary"
          onClick={() => onOpenArtifact(artifact)}
        >
          <WorkspacePreviewExpandIcon />
          <span>Expand</span>
        </button>
        <a
          href={artifactOpenUrl(artifact)}
          target="_blank"
          rel="noreferrer"
          className="workspace-sidepanel__preview-action"
        >
          <WorkspacePreviewExpandIcon />
          <span>Open</span>
        </a>
        <a
          href={artifactDownloadUrl(artifact)}
          download={artifact.name}
          className="workspace-sidepanel__preview-action"
        >
          <WorkspacePreviewDownloadIcon />
          <span>Download</span>
        </a>
      </div>
    </div>
  );
}

export function WorkspaceSidePanelPreviewPanel({
  activePreviewPath,
  openPreviewEntries,
  selectedEntry,
  onClosePreviewPath,
  onOpenArtifact,
  onSelectPreviewPath,
}: {
  activePreviewPath: string;
  openPreviewEntries: WorkspaceFileEntry[];
  selectedEntry: WorkspaceFileEntry | null;
  onClosePreviewPath: (relativePath: string) => void;
  onOpenArtifact: (artifact: ToolArtifact) => void;
  onSelectPreviewPath: (relativePath: string) => void;
}) {
  if (!selectedEntry) {
    return <WorkspacePreviewEmptyState />;
  }

  const artifact = asArtifact(selectedEntry);
  const kind = classifyArtifact(artifact);

  return (
    <section className="workspace-sidepanel__preview-panel">
      <div className="workspace-sidepanel__preview-chrome">
        <div className="workspace-sidepanel__preview-overview">
          <div className="workspace-sidepanel__preview-overview-copy">
            <span className="workspace-sidepanel__section-title">Preview</span>
            {openPreviewEntries.length > 1 ? (
              <span className="workspace-sidepanel__section-meta">
                {openPreviewEntries.length} open
              </span>
            ) : null}
          </div>
          <span className="workspace-sidepanel__preview-kind">{kind}</span>
        </div>
        <WorkspaceSidePanelPreviewTabs
          activePreviewPath={activePreviewPath}
          openPreviewEntries={openPreviewEntries}
          onCloseTab={onClosePreviewPath}
          onSelectTab={onSelectPreviewPath}
        />
        <WorkspacePreviewHeader
          artifact={artifact}
          entry={selectedEntry}
          onOpenArtifact={onOpenArtifact}
        />
      </div>
      <div
        className={`workspace-sidepanel__preview-surface workspace-sidepanel__preview-surface--${kind}`}
      >
        <ArtifactPreviewBody artifact={artifact} kind={kind} />
      </div>
    </section>
  );
}
