import { useState } from "react";
import { originalContentUrl } from "../../../admin/components/workspaceKnowledge/workspaceKnowledgeRequest";
import type { SourceDetail } from "../../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import { DataTable } from "../../../layout/DataTable";
import { SidePanel } from "../../../layout/SidePanel";
import { StatusLabel } from "../../../layout/StatusLabel";
import { KnowledgeSourceRemoval } from "../KnowledgeSourceRemoval";
import { formatSize, isRemovedSource, mayOpenOriginal, mediaLabel, originalActionLabel, revisionLabel } from "../sourceInventoryModel";
import { removalConsequences, removedSourceNote, syncedOriginOf } from "../syncedSourceModel";
import { DocumentDiffTab } from "./DocumentDiffTab";
import { DocumentViewTab } from "./DocumentViewTab";
import type { DocumentRevision } from "./DocumentViewTab";
import { shownRevision } from "./documentViewModel";
import "./knowledge-document.css";

type Tab = "view" | "revisions" | "diff";

// One document in the side panel (or as a page): View the original in place, its Revisions, and the Diff of two.
// The facts on top (where it was synced from, whether it was removed) stay visible on every tab; authors remove
// the document from the footer.
export function KnowledgeDocumentPanel({ workspaceId, sourceId, title, detail, error, mayAuthor, mode = "panel",
  pageHref, backHref, onRemoved, onClose }: {
  workspaceId: string;
  sourceId: string;
  title: string;
  detail: SourceDetail | null;
  error: string | null;
  mayAuthor: boolean;
  mode?: "panel" | "page";
  pageHref?: string;
  backHref?: string;
  onRemoved: () => void;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<Tab>("view");
  const [viewId, setViewId] = useState<string | null>(null);
  const removed = isRemovedSource(detail);
  const synced = syncedOriginOf(detail);
  const revisions = (detail?.revisions ?? []) as DocumentRevision[];
  const shown = revisions.find((revision) => revision.revision_id === viewId) ?? shownRevision(revisions);
  const shownTitle = detail?.display_title ?? title;
  const tabs = {
    label: `Views of ${shownTitle}`,
    idPrefix: `document-${sourceId}`,
    value: tab,
    onChange: (next: string) => setTab(next as Tab),
    tabs: [
      { key: "view", label: "View" },
      { key: "revisions", label: "Revisions", count: revisions.length || undefined },
      { key: "diff", label: "Diff", disabled: revisions.length < 2 },
    ],
  };
  const facts = <div className="document-panel__facts">
    {synced ? <p className="document-view__meta">Synced from {synced.sourceName}.
      {synced.url ? <> <a href={synced.url} target="_blank" rel="noopener noreferrer"
        data-testid="source-drawer-origin-link">Open in {synced.sourceName}</a></> : null}</p>
      : <p className="document-view__meta">Uploaded document.</p>}
    {removed ? <p className="document-view__meta" data-testid="source-drawer-removed">{removedSourceNote(synced)}</p> : null}
  </div>;
  let body;
  if (error) body = <p role="alert">{error}</p>;
  else if (!detail) body = <p role="status">Loading the document…</p>;
  else if (tab === "view") body = <DocumentViewTab workspaceId={workspaceId} sourceId={detail.source_id} revision={shown} />;
  else if (tab === "diff") body = <DocumentDiffTab workspaceId={workspaceId} sourceId={detail.source_id} revisions={revisions} />;
  else {
    body = <DataTable<DocumentRevision> label="Revisions" testId="document-revisions" rows={revisions}
      rowKey={(revision) => revision.revision_id}
      selectedKey={shown?.revision_id ?? null}
      onOpen={(revision) => { if (mayOpenOriginal(revision.state)) { setViewId(revision.revision_id); setTab("view"); } }}
      columns={[
        { key: "ordinal", header: "Revision", nowrap: true, render: (revision) => `#${revision.revision_ordinal}` },
        { key: "state", header: "State", nowrap: true, render: (revision) => <StatusLabel label={revisionLabel(revision.state)} /> },
        { key: "type", header: "Type", nowrap: true, render: (revision) => mediaLabel(revision.media_type) },
        { key: "size", header: "Size", nowrap: true, align: "end", render: (revision) => formatSize(revision.byte_size) },
        { key: "passages", header: "Passages", nowrap: true, align: "end", render: (revision) => String(revision.span_count) },
        { key: "original", header: "Original", nowrap: true, render: (revision) => mayOpenOriginal(revision.state)
          ? <a href={originalContentUrl(workspaceId, detail.source_id, revision.revision_id)} target="_blank"
            rel="noopener noreferrer" onClick={(event) => event.stopPropagation()}>{originalActionLabel(revision.media_type)}</a>
          : "—" },
      ]} />;
  }
  const footer = mayAuthor && !removed && detail
    ? <KnowledgeSourceRemoval workspaceId={workspaceId} sourceId={sourceId} title={shownTitle} onRemoved={onRemoved}
      consequences={removalConsequences(synced)} />
    : undefined;
  return <SidePanel title={shownTitle} subtitle={detail ? `${revisions.length} revision${revisions.length === 1 ? "" : "s"}` : undefined}
    onClose={onClose} mode={mode} pageHref={mode === "panel" ? pageHref : undefined} testId="knowledge-document"
    headerActions={mode === "page" && backHref ? <a className="admin-panel__action-btn" href={backHref}>← All documents</a> : undefined}
    tabs={tabs} footer={footer}>
    {facts}
    {body}
  </SidePanel>;
}
