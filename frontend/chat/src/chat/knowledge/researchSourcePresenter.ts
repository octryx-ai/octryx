// Rules of Knowledge → Research websites, mirrored from the backend so the page explains them and warns
// before a request that the server would treat differently than the person expects:
// - backend/app/api/routes/web_search_sources.py (SourceRequest bounds),
// - backend/app/services/web_search/patterns.py (normalize_pattern),
// - backend/app/services/web_search/registry.py (put_source re-decides an existing pattern in the same scope).

import type { TrustedSource, WebSearchOverview } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";

export const MAX_PATTERN_CHARS = 300;
export const MIN_PATTERN_CHARS = 4;
export const MAX_REASON_CHARS = 500;
export const MAX_PRODUCTS = 8;

export type SourceDecision = "trusted" | "blocked";

export const STATE_LABELS: Record<TrustedSource["state"], string> = {
  trusted: "Approved",
  proposed: "Awaiting review",
  blocked: "Blocked",
};

export const STATE_BADGES: Record<TrustedSource["state"], string> = {
  trusted: "admin-panel__badge--active",
  proposed: "admin-panel__badge--warning",
  blocked: "admin-panel__badge--danger",
};

// What the workspace's search mode means, in plain words.
export function modeExplanation(mode: WebSearchOverview["mode"]): string {
  return mode === "trusted_only"
    ? "Approved websites only: chat web search and research read only from websites approved below. Anything else is skipped."
    : "Open: chat web search may use any website except blocked ones. Research always reads only approved websites.";
}

// The canonical form the server stores (host lower-cased, no "www.", no scheme, no empty path segments),
// so the page can tell that two spellings name the same entry. Null when it cannot be a pattern at all.
export function normalizeSourcePattern(raw: string): string | null {
  const text = raw.trim();
  if (text.length < MIN_PATTERN_CHARS || text.length > MAX_PATTERN_CHARS) return null;
  let parts: URL;
  try {
    parts = new URL(text.includes("://") ? text : `https://${text}`);
  } catch {
    return null;
  }
  if (!["https:", "http:"].includes(parts.protocol) || parts.username || parts.password || parts.port) return null;
  let host = parts.hostname.toLowerCase().replace(/^\.+|\.+$/g, "");
  if (host.startsWith("www.")) host = host.slice(4);
  if (!host.includes(".")) return null;
  const path = parts.pathname.split("/").filter(Boolean).join("/");
  return path ? `${host}/${path}` : host;
}

// Why a pattern needs a fix before it is sent; null when it looks acceptable (the server still decides).
export function patternProblem(raw: string): string | null {
  const text = raw.trim();
  if (!text) return null;
  if (text.length > MAX_PATTERN_CHARS) return `A website pattern can have at most ${MAX_PATTERN_CHARS} characters.`;
  if (text.includes("*")) return "Wildcards are not needed: a host covers its subdomains and a path covers everything below it.";
  if (normalizeSourcePattern(text) === null) return "Enter a host such as docs.spring.io, optionally with a path.";
  return null;
}

// An existing entry in the same scope with the same canonical pattern. Saving re-decides that entry.
export function existingEntry(
  sources: TrustedSource[], raw: string, scope: TrustedSource["scope"],
): TrustedSource | null {
  const canonical = normalizeSourcePattern(raw);
  if (!canonical) return null;
  return sources.find((source) => source.scope === scope && source.pattern === canonical) ?? null;
}

export function redecisionWarning(existing: TrustedSource | null, decision: SourceDecision): string | null {
  if (!existing) return null;
  if (existing.state === decision) {
    return `${existing.pattern} is already ${STATE_LABELS[existing.state].toLowerCase()}. Saving replaces its products and reason.`;
  }
  return `${existing.pattern} is currently ${STATE_LABELS[existing.state].toLowerCase()}. Saving changes the decision to ${
    decision === "trusted" ? "approved" : "blocked"}.`;
}

export function mayDecideSource(source: TrustedSource, mayAuthor: boolean, mayEditPlatform: boolean): boolean {
  return mayAuthor && (source.scope === "workspace" || mayEditPlatform);
}
