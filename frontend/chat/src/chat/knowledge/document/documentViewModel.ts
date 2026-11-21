// Knowledge › Documents: the original of a revision shown in place, and the change between two revisions
// (inventory: show the original in place; with several revisions, the diff side by side). Pure functions only.
// The backend sanitizes HTML (allowlist); the page strips active content again before it renders it in a
// sandboxed frame, so a sanitizer gap never runs a script here.

import { mayOpenOriginal } from "../sourceInventoryModel";

/** The revision shown first: the newest one whose original may be opened. */
export function shownRevision<Revision extends { revision_ordinal: number; state: string }>(revisions: Revision[]): Revision | null {
  return [...revisions].sort((left, right) => right.revision_ordinal - left.revision_ordinal)
    .find((revision) => mayOpenOriginal(revision.state)) ?? null;
}

export type DocumentView = {
  revision_id: string;
  revision_ordinal?: number;
  content_type: string;
  byte_size?: number;
  source_url?: string | null;
  source_changed_at?: string | null;
  state: "ok" | "too_large";
  html: string | null;
  text: string | null;
};

export type DiffSide = { revision_id: string; revision_ordinal?: number; content_type?: string; source_changed_at?: string | null };

export type DocumentDiff = {
  state: "ok" | "identical" | "too_large";
  too_large_reason?: string | null;
  diff: string | null;
  stats: { added_lines: number; removed_lines: number } | null;
  from: DiffSide;
  to: DiffSide;
};

/** One plain sentence per coded refusal of the original routes. */
export const ORIGINAL_ERROR_TEXT: Record<string, string> = {
  workspace_not_found: "This workspace is not available to you.",
  revision_not_found: "This revision no longer exists or is not visible to you.",
  original_not_stored: "No original is stored for this revision.",
  original_object_missing: "The original of this revision is missing in storage.",
  original_location_mismatch: "The original of this revision is stored outside this installation.",
  original_not_displayable: "This original cannot be shown here. Download it instead.",
};

export function originalErrorText(code: string | null | undefined, fallback?: string): string {
  return (code && ORIGINAL_ERROR_TEXT[code]) || fallback || "The original could not be loaded.";
}

export const isPdf = (contentType: string | null | undefined) => /^application\/pdf\b/i.test(contentType ?? "");

/** Markdown (an uploaded .md, or a synced page or record, which Knowledge stores as Markdown) is shown rendered. */
export const isMarkdown = (contentType: string | null | undefined) => /^text\/(x-)?markdown\b/i.test(contentType ?? "");

const ACTIVE_ELEMENTS = /<(script|style|iframe|frame|frameset|object|embed|link|meta|base|form|template)\b[^>]*>[\s\S]*?<\/\1\s*>|<(script|style|iframe|frame|object|embed|link|meta|base|form|input|button|template)\b[^>]*\/?>/gi;
const EVENT_ATTRIBUTES = /\s+on[a-z]+\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi;
const SCRIPT_URLS = /\s+(href|src|xlink:href|action|formaction|srcdoc)\s*=\s*("\s*(javascript|vbscript|data):[^"]*"|'\s*(javascript|vbscript|data):[^']*'|(javascript|vbscript|data):[^\s>]+)/gi;
const SRCDOC = /\s+srcdoc\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)/gi;

/** Removes scripts, frames, forms, event handlers and script URLs; the rest is the backend's sanitized HTML. */
export function stripActiveContent(html: string): string {
  let out = html;
  // Repeat until stable, so nested or split tags cannot reassemble into an active one.
  for (let round = 0; round < 3; round += 1) {
    const next = out.replace(ACTIVE_ELEMENTS, "").replace(EVENT_ATTRIBUTES, "").replace(SCRIPT_URLS, "").replace(SRCDOC, "");
    if (next === out) break;
    out = next;
  }
  return out;
}

/** The sandboxed frame's whole document: the sanitized body with a calm reading style, no scripts allowed. */
export function viewDocument(html: string): string {
  const style = "body{font:14px/1.55 system-ui,sans-serif;margin:16px;color:#1e1d1a;background:#fff;overflow-wrap:anywhere}"
    + "img{max-width:100%;height:auto}table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 6px}"
    + "pre,code{white-space:pre-wrap}";
  return `<!doctype html><html><head><meta charset="utf-8"><style>${style}</style></head><body>${stripActiveContent(html)}</body></html>`;
}

/** "+12 −3" (lines added, removed). */
export function diffStatsText(stats: DocumentDiff["stats"]): string {
  if (!stats) return "";
  return `+${stats.added_lines} −${stats.removed_lines}`;
}

export type DiffCell = { line: number; text: string; kind: "same" | "removed" | "added" } | null;
export type DiffRow = { left: DiffCell; right: DiffCell; hunk?: string };

/** A unified diff as side-by-side rows: removed lines left, added lines right, paired in order within a change. */
export function sideBySide(unified: string | null | undefined): DiffRow[] {
  const rows: DiffRow[] = [];
  let left = 0;
  let right = 0;
  let removed: { line: number; text: string }[] = [];
  let added: { line: number; text: string }[] = [];
  const flush = () => {
    const count = Math.max(removed.length, added.length);
    for (let index = 0; index < count; index += 1) {
      const gone = removed[index];
      const come = added[index];
      rows.push({
        left: gone ? { ...gone, kind: "removed" } : null,
        right: come ? { ...come, kind: "added" } : null,
      });
    }
    removed = [];
    added = [];
  };
  for (const raw of (unified ?? "").split("\n")) {
    if (raw.startsWith("---") || raw.startsWith("+++")) continue;
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@(.*)$/.exec(raw);
    if (hunk) {
      flush();
      left = Number(hunk[1]);
      right = Number(hunk[2]);
      rows.push({ left: null, right: null, hunk: raw });
      continue;
    }
    if (raw.startsWith("-")) { removed.push({ line: left, text: raw.slice(1) }); left += 1; continue; }
    if (raw.startsWith("+")) { added.push({ line: right, text: raw.slice(1) }); right += 1; continue; }
    if (raw.startsWith(" ")) {
      flush();
      rows.push({ left: { line: left, text: raw.slice(1), kind: "same" }, right: { line: right, text: raw.slice(1), kind: "same" } });
      left += 1;
      right += 1;
    }
  }
  flush();
  return rows;
}

export const DOCUMENT_PARAM = "document";
export const DOCUMENT_VIEW_PARAM = "document_view";

/** The address of a document's panel (or, with `page`, the same detail full width); every other parameter stays. */
export function documentHref(search: string, sourceId: string | null, page = false): string {
  const params = new URLSearchParams(search);
  params.delete(DOCUMENT_PARAM);
  params.delete(DOCUMENT_VIEW_PARAM);
  if (sourceId) params.set(DOCUMENT_PARAM, sourceId);
  if (sourceId && page) params.set(DOCUMENT_VIEW_PARAM, "page");
  const query = params.toString();
  return query ? `?${query}` : "?";
}

export function requestedDocument(search: string): { sourceId: string | null; page: boolean } {
  const params = new URLSearchParams(search);
  const sourceId = params.get(DOCUMENT_PARAM);
  return { sourceId: sourceId || null, page: Boolean(sourceId) && params.get(DOCUMENT_VIEW_PARAM) === "page" };
}
