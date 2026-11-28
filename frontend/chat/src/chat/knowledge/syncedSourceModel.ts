// The origin comes from stored lineage, never guessed from the source key.

import { REMOVE_SOURCE_CONSEQUENCES } from "./sourceInventoryModel";

export type SyncedOrigin = {
  sourceName: string;
  noun: string;
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

// Absolute http(s) only: no javascript:, data: or relative links.
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

export function removedSourceNote(origin: SyncedOrigin | null): string {
  if (!origin) return `This document was removed from search. ${UPLOAD_AGAIN}`;
  if (origin.removedAtSource) {
    return `This ${origin.noun} was deleted or moved out of the synced scope in ${origin.sourceName}, so it was removed from search.`;
  }
  return `This ${origin.noun} was removed from this Workspace's search.`;
}

export function removalConsequences(origin: SyncedOrigin | null): string[] {
  return origin
    ? REMOVE_SOURCE_CONSEQUENCES.filter((line) => line !== UPLOAD_AGAIN)
    : [...REMOVE_SOURCE_CONSEQUENCES];
}

export function documentOriginLine(source: { origin?: unknown } | null | undefined): string {
  const origin = syncedOriginOf(source);
  return origin ? `From ${origin.sourceName}` : "Uploaded";
}
