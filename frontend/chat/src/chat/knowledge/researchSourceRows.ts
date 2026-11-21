// Row and provider presentation of Knowledge → Research websites: what each table cell shows,
// which decision actions a row offers, and the one-line provider status of the collapsed provider section.
// The decision rules themselves live in researchSourcePresenter.ts; the server still enforces them.

import type { TrustedSource, WebSearchOverview } from "../../admin/components/workspaceKnowledge/workspaceKnowledgeTypes";
import { safeSourceUrl } from "../evidence/answerSourceLinks";
import { STATE_BADGES, STATE_LABELS, mayDecideSource } from "./researchSourcePresenter";
import type { StatusTone } from "../../layout/StatusLabel";

export type ResearchActionKey = "trusted" | "blocked" | "remove";

export type ResearchAction = { key: ResearchActionKey; label: string; tone: "primary" | "danger" | "default" };

export type ResearchMeta = { label: string; value: string };

// The decision as a state label: only an open proposal asks for attention; a block is a problem.
export const STATE_TONES: Record<TrustedSource["state"], StatusTone> = { proposed: "attention", trusted: "success", blocked: "problem" };

export type ResearchSourceRow = {
  id: string;
  state: TrustedSource["state"];
  pattern: string;
  reason: string;
  // Full reason for the clamped cell; absent when there is no recorded reason.
  reasonTitle?: string;
  evidenceUrl: string | null;
  stateLabel: string;
  badge: string;
  meta: ResearchMeta[];
  actions: ResearchAction[];
  // Why a row offers no actions; null when it does.
  readOnlyNote: string | null;
};

// The same actions: Approve unless approved, Block unless blocked, always Remove.
export function researchActions(source: TrustedSource): ResearchAction[] {
  const actions: ResearchAction[] = [];
  if (source.state !== "trusted") actions.push({ key: "trusted", label: "Approve", tone: "primary" });
  if (source.state !== "blocked") actions.push({ key: "blocked", label: "Block", tone: "danger" });
  actions.push({ key: "remove", label: "Remove", tone: "default" });
  return actions;
}

export function researchSourceRow(
  source: TrustedSource,
  context: { mayAuthor: boolean; mayEditPlatform: boolean; origin: string },
): ResearchSourceRow {
  const editable = mayDecideSource(source, context.mayAuthor, context.mayEditPlatform);
  const reason = source.reason.trim();
  return {
    id: source.id,
    state: source.state,
    pattern: source.pattern,
    reason: reason || "No reason recorded.",
    reasonTitle: reason || undefined,
    evidenceUrl: source.evidence_url ? safeSourceUrl(source.evidence_url, context.origin) : null,
    stateLabel: STATE_LABELS[source.state],
    badge: STATE_BADGES[source.state],
    meta: [
      { label: "Applies to", value: source.scope === "platform" ? "All workspaces" : "This workspace" },
      { label: "Products", value: source.products.join(", ") || "All" },
      { label: "Proposed by", value: source.origin === "agent" ? "Research agent" : "Administrator" },
    ],
    actions: editable ? researchActions(source) : [],
    readOnlyNote: editable ? null : source.scope === "platform" && context.mayAuthor ? "Platform admin only" : "View only",
  };
}

const PROVIDER_STATE_LABELS: Record<string, string> = {
  ok: "Working",
  unavailable: "Unavailable",
  needs_configuration: "Needs configuration",
};

export const PROVIDER_BADGES: Record<string, string> = {
  ok: "admin-panel__badge--active",
  unavailable: "admin-panel__badge--danger",
  needs_configuration: "admin-panel__badge--warning",
};

export function providerStateLabel(state: string): string {
  const known = PROVIDER_STATE_LABELS[state];
  if (known) return known;
  const words = state.replaceAll("_", " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "Unknown";
}

// A search provider's name as people know it ("tavily" was shown as the raw id).
const PROVIDER_NAMES: Record<string, string> = {
  tavily: "Tavily", brave: "Brave Search", serper: "Serper", serpapi: "SerpApi", searxng: "SearXNG", bing: "Bing",
  google: "Google", exa: "Exa", perplexity: "Perplexity", duckduckgo: "DuckDuckGo",
};

export function providerDisplayName(name: string | null | undefined): string | null {
  if (!name) return null;
  const known = PROVIDER_NAMES[name.toLowerCase()];
  if (known) return known;
  const words = name.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : name;
}

// "Search provider: Tavily · Working" — the status a reader needs without opening the provider section.
export function providerSummary(provider: WebSearchOverview["provider"]): {
  text: string; stateLabel: string; badge: string; attention: boolean;
} {
  const stateLabel = providerStateLabel(provider.state);
  const name = providerDisplayName(provider.name) ?? "not configured";
  const showState = Boolean(provider.name) || provider.state !== "needs_configuration";
  return {
    text: `Search provider: ${name}${showState ? ` · ${stateLabel}` : ""}`,
    stateLabel,
    badge: PROVIDER_BADGES[provider.state] ?? "admin-panel__badge--inactive",
    attention: !provider.name || provider.state !== "ok",
  };
}
