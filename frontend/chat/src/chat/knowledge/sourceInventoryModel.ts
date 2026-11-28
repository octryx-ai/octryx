import { DEFAULT_SOURCE_LIMIT } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeRequest";
import type { KnowledgeSource, SourceDetail } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";

export const REVISION_LABELS: Record<string, string> = {
  registered: "Received, not indexed yet",
  projected: "Indexed",
  superseded: "Previous revision",
  tombstoned: "Removed from search",
};

export function revisionLabel(state: string): string {
  return REVISION_LABELS[state] ?? "Status unavailable";
}

// The endpoint answers 404 for a removed source's bytes, so no link is offered.
export function mayOpenOriginal(state: string): boolean {
  return state !== "tombstoned";
}

export function sourceListingSummary(loaded: number, hasMore: boolean, query: string): string {
  const scope = query.trim() ? ` matching “${query.trim()}”` : "";
  if (!loaded) return query.trim() ? `No document title or key matches “${query.trim()}”.` : "No documents in this workspace yet.";
  return hasMore
    ? `Showing the newest ${loaded} documents${scope}; load more to see older ones.`
    : `Showing all ${loaded} ${loaded === 1 ? "document" : "documents"}${scope}.`;
}

export const INITIAL_SOURCE_LIMIT = DEFAULT_SOURCE_LIMIT;

export function formatSize(bytes: number): string {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${Math.max(1, Math.ceil(bytes / 1024))} KB`;
}

const MEDIA_LABELS: Record<string, string> = {
  "application/pdf": "PDF",
  "text/plain": "Text",
  "text/markdown": "Markdown",
  "text/asciidoc": "AsciiDoc",
  "text/csv": "CSV",
  "text/html": "HTML",
  "application/json": "JSON",
  "application/xml": "XML",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word",
  "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel",
};

export function mediaLabel(mediaType: string): string {
  return MEDIA_LABELS[mediaType] ?? mediaType;
}

// Only PDF opens in the browser; the server sends everything else as a download.
export function originalActionLabel(mediaType: string): string {
  return mediaType === "application/pdf" ? "Open original" : "Download original";
}

export function revisionSummary(count: number, latest: number | null): string {
  const total = Math.max(0, Math.floor(Number(count) || 0));
  if (!total) return latest === null ? "No revisions" : `Latest #${latest}`;
  const counted = `${total} ${total === 1 ? "revision" : "revisions"}`;
  return latest === null || (total === 1 && latest === 1) ? counted : `${counted} · latest #${latest}`;
}

export type SourceRow = { id: string; title: string; key: string; revisions: string };

export function sourceRow(source: KnowledgeSource): SourceRow {
  const key = source.source_key ?? "";
  return {
    id: source.source_id,
    title: source.display_title?.trim() || key || "Untitled document",
    key,
    revisions: revisionSummary(source.revision_count, source.latest_revision_ordinal),
  };
}

export const REMOVE_SOURCE_CONSEQUENCES = [
  "The document leaves this workspace's searchable knowledge.",
  "Its history stays in the evidence ledger.",
  "Uploading the same file again brings it back.",
];

export function removedNotice(title: string): string {
  return `“${title}” was removed from this workspace's searchable knowledge.`;
}

export function isRemovedSource(detail: SourceDetail | null): boolean {
  const revisions = detail?.revisions ?? [];
  return revisions.length > 0 && revisions.every((revision) => revision.state === "tombstoned");
}
