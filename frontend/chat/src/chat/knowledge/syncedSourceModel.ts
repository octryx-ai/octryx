// Where a document in Knowledge → Documents comes from. Pure: no requests, no React.
//
// A synced source (a Confluence page, Jira issue, … of a Source Sync connector) is not an upload: it is not
// "uploaded again", it links to its page at the source, and when the page is deleted or moved out of the
// synced scope the connector retires it ("removed at source").
//
// Each source of GET …/knowledge/sources and GET …/knowledge/sources/{id} carries its origin from stored lineage
// (backend `knowledge/sources/sync/source_origins.py`):
//   origin: { type: "upload" }
//         | { type: "connector", connector_kind, connector_key, url: string | null, removed_at_source: boolean }
// The origin is never guessed from the source key.

import { REMOVE_SOURCE_CONSEQUENCES } from "./sourceInventoryModel";

export type SyncedOrigin = {
  /** "Confluence", "Jira", … for the page or item's home. */
  sourceName: string;
  /** "page", "issue", … */
  noun: string;
  /** An http(s) address of the item at its source, else null. */
  url: string | null;
  removedAtSource: boolean;
};

const SOURCE: Record<string, [string, string]> = {
  confluence: ["Confluence", "page"],
  jira: ["Jira", "issue"],
  servicenow: ["ServiceNow", "article or record"],
  git_repository: ["the repository", "file"],
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

/** An absolute http(s) address, else null (no javascript:, data: or relative links). */
export function safeSourceUrl(value: unknown): string | null {
  if (typeof value !== "string" || !/^https?:\/\//i.test(value.trim()))
    return null;
  try {
    const parsed = new URL(value.trim());
    return parsed.protocol === "https:" || parsed.protocol === "http:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

/** The synced origin of a source or source detail, or null for an upload. */
export function syncedOriginOf(
  source: { origin?: unknown } | null | undefined,
): SyncedOrigin | null {
  const origin = source?.origin;
  if (!isRecord(origin) || origin.type !== "connector") return null;
  const kind =
    typeof origin.connector_kind === "string" ? origin.connector_kind : "";
  const [sourceName, noun] = SOURCE[kind] ?? ["the source system", "item"];
  return {
    sourceName,
    noun,
    url: safeSourceUrl(origin.url),
    removedAtSource: origin.removed_at_source === true,
  };
}

const UPLOAD_AGAIN = "Uploading the same file again brings it back.";

/** The drawer's note for a document whose every revision is removed from search. */
export function removedSourceNote(origin: SyncedOrigin | null): string {
  if (!origin) return `This document was removed from search. ${UPLOAD_AGAIN}`;
  if (origin.removedAtSource) {
    return `This ${origin.noun} was deleted or moved out of the synced scope in ${origin.sourceName}, so it was removed from search.`;
  }
  return `This ${origin.noun} was removed from this Workspace's search.`;
}

/** What removing a document does; a synced item is not brought back by uploading it. */
export function removalConsequences(origin: SyncedOrigin | null): string[] {
  return origin
    ? REMOVE_SOURCE_CONSEQUENCES.filter((line) => line !== UPLOAD_AGAIN)
    : [...REMOVE_SOURCE_CONSEQUENCES];
}

/** Where a document comes from, for its row (instead of its internal key): "From Confluence", else "Uploaded". */
export function documentOriginLine(source: { origin?: unknown } | null | undefined): string {
  const origin = syncedOriginOf(source);
  return origin ? `From ${origin.sourceName}` : "Uploaded";
}
