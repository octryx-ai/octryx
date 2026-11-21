// Pure rules of the Knowledge → Search entry overview, stated only from existing API fields (no invented totals
// or dates).
//
// - Whether the workspace holds documents comes from the first newest-first page of /knowledge/sources; a next
//   cursor means "more".
// - The indexing backlog comes from `projection_backlog`, the per-state count of indexing jobs of the workspace
//   (backend models/project/knowledge_evidence.py OUTBOX_STATE_*: pending, claimed, applied, dead_letter).
// - Research websites come from /web-search/sources (mode and decided entries).

import type { SourceListing, WebSearchOverview } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";

export function hasNoDocuments(listing: Pick<SourceListing, "sources" | "next_cursor"> | null): boolean {
  return Boolean(listing && !listing.sources.length && !listing.next_cursor);
}

export function plural(count: number, one: string, many: string): string {
  return `${count} ${count === 1 ? one : many}`;
}

// Indexing jobs per state (jobs, not documents: one document can have several). "Waiting" covers
// queued and running jobs; failed jobs need attention.
export function indexingJobs(listing: Pick<SourceListing, "projection_backlog">): { indexed: number; waiting: number; failed: number } {
  const backlog = listing.projection_backlog ?? {};
  const count = (state: string) => Math.max(0, Number(backlog[state]) || 0);
  return { indexed: count("applied"), waiting: count("pending") + count("claimed"), failed: count("dead_letter") };
}

export function researchCounts(overview: WebSearchOverview | null): { approved: number; proposed: number } {
  const sources = overview?.sources ?? [];
  return {
    approved: sources.filter((source) => source.state === "trusted").length,
    proposed: sources.filter((source) => source.state === "proposed").length,
  };
}

export function approveActionLabel(overview: WebSearchOverview | null): string {
  const { proposed } = researchCounts(overview);
  return proposed ? `Approve research websites (${proposed})` : "Approve research websites";
}
