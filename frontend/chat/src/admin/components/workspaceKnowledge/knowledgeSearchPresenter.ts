// Pure presentation rules of Knowledge → Search: toolbar hint and options label, the results header,
// passage clamping, the meta line of a hit and the per-mode search availability. Counts are always the
// count of returned evidence, never a total of the workspace.

import type { EvidenceHit } from "./workspaceKnowledgeTypes";

export const DEFAULT_SEARCH_MODE = "hybrid";

export function searchHint(emptyWorkspace: boolean): string {
  return emptyWorkspace
    ? "No documents yet; search also covers knowledge shared with this workspace."
    : "Ask in any language; every passage links to its source.";
}

// Options that narrow or change the search; a version only counts when a product scopes it, because
// the request drops a version without products.
export function activeOptionCount(options: { mode: string; products: string; version: string }): number {
  const products = options.products.trim().length > 0;
  return Number(options.mode !== DEFAULT_SEARCH_MODE) + Number(products) + Number(products && options.version.trim().length > 0);
}

export function optionsLabel(active: number): string {
  return active ? `Options (${active} active)` : "Options";
}

export function resultCountLabel(count: number, query: string): string {
  const subject = count === 0 ? "No source passages" : count === 1 ? "1 source passage" : `${count} source passages`;
  return `${subject} for “${query}”`;
}

// A passage is clamped to three lines only when it is likely longer than that; a short passage is shown
// whole, so the clamp can never hide text without offering "Show full passage".
export const PASSAGE_CLAMP_CHARS = 220;
export const PASSAGE_CLAMP_LINES = 3;

export function passageNeedsExpand(text: string): boolean {
  const passage = text.trim();
  return passage.length > PASSAGE_CLAMP_CHARS || passage.split("\n").length > PASSAGE_CLAMP_LINES;
}

export function hitMetaLine(hit: Pick<EvidenceHit, "products" | "version" | "bound" | "workspace">): string {
  const parts: string[] = [];
  if (hit.bound) parts.push(`Shared from ${hit.workspace || "another workspace"}`);
  if (hit.products.length) parts.push(hit.products.join(", "));
  if (hit.products.length && hit.version) parts.push(hit.version);
  return parts.join(" · ");
}

export type AvailabilityRow = { key: string; label: string; state: string; ok: boolean };

const MODE_LABELS: Record<string, string> = {
  lexical: "Keyword search", vector: "Meaning search", graph: "Graph search", rerank: "Reranking",
};
const STATE_LABELS: Record<string, string> = {
  ok: "Available", needs_configuration: "Needs configuration", denied: "Denied",
  unavailable: "Unavailable", contract_violation: "Contract violation", invalid_request: "Invalid request",
};

function humanize(code: string): string {
  const words = code.replace(/[_-]+/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : code;
}

// One row per mode the server reported, in the server's order; unknown codes are shown, not hidden.
export function availabilityRows(states: Record<string, string> | null | undefined): AvailabilityRow[] {
  return Object.entries(states ?? {}).map(([key, state]) => ({
    key,
    label: MODE_LABELS[key] ?? humanize(key),
    state: STATE_LABELS[state] ?? humanize(String(state)),
    ok: state === "ok",
  }));
}

export function availabilitySummary(rows: AvailabilityRow[]): string {
  const available = rows.filter((row) => row.ok).length;
  if (rows.length === 1) return rows[0].ok ? "available" : rows[0].state.toLowerCase();
  return available === rows.length ? `all ${rows.length} available` : `${available} of ${rows.length} available`;
}

// ---- Relevance (library-search-relevance-ui) ----------------------------
//
// Read from the server, never guessed: the search answer's `mode_states.rerank` (this search) and the Knowledge
// settings read model (`GET …/knowledge/settings`: `data_classification {effective, source}` and
// `reranker {state, hold_reason}`). Only hybrid search is reranked; keyword and meaning search are not
// relevance-filtered.

export const SEARCH_MODES: { value: string; label: string }[] = [
  { value: "hybrid", label: "Hybrid: keywords and meaning, relevance-ranked when the reranker is available" },
  { value: "lexical", label: "Keyword: the exact terms, not relevance-filtered" },
  { value: "vector", label: "Meaning: similar meaning, not relevance-filtered" },
];

/** What the chosen method does; `rerank` is whether relevance ranking is active (null when not reported). */
export function searchModeHint(mode: string, rerank: boolean | null): string {
  if (mode !== "hybrid") return "Not relevance-filtered: results may be only loosely related to the question.";
  if (rerank === true) return "Ranked by relevance; passages the reranker judges irrelevant are left out.";
  if (rerank === false) {
    return "Relevance ranking is unavailable, so results are ranked by keywords and meaning only and may be loosely related.";
  }
  return "Ranked by relevance when the reranker is available.";
}

// The reranker's closed hold reasons (rerank/admission_state.py, embedding/selection.admit_remote), each with who
// can fix it.
const HOLD_TEXT: Record<string, string> = {
  reranker_not_configured:
    "no reranker is configured for this instance; an instance operator can set one up",
  reranker_unknown: "the configured reranker is not known; an instance operator corrects the reranker setting",
  // Runtime holds (embedding/bedrock.bedrock_runtime_hold).
  region_missing:
    "no AWS region is set for the reranker on this instance; an instance operator sets it",
  runtime_missing:
    "this instance cannot reach the reranker; an instance operator completes its installation",
  workspace_data_classification_missing:
    "this Workspace has no data classification; a Workspace admin sets it, or an instance operator sets an Instance default",
  workspace_data_classification_unknown: "this Workspace's data classification is not recognised; a Workspace admin corrects it",
  data_policy_class_insufficient:
    "this Workspace's data classification is more sensitive than the reranker may receive; only a Workspace admin changing the classification, or an instance operator providing a reranker allowed for it, changes this",
};

/** A reranker hold reason in words with who can fix it, or null for a code that is not a hold. */
export function rerankerHoldText(reason: string | null | undefined): string | null {
  return reason ? HOLD_TEXT[reason] ?? null : null;
}

const STATE_TEXT: Record<string, string> = {
  needs_configuration: "the reranker needs configuration; an instance operator or a Workspace admin can check the Knowledge settings",
  denied: "this Workspace's data policy does not allow the reranker; a Workspace admin can check its data classification",
  unavailable: "the reranker is not reachable right now; try again later",
};

const SOURCE_TEXT: Record<string, string> = {
  workspace: "set for this Workspace",
  instance_default: "Instance default",
  unset: "not set",
};

export type RelevanceStatus = { active: boolean; text: string; classification: string | null };

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** "Relevance ranking active" or "Relevance ranking unavailable: <reason; who can fix it>"; null when not reported. */
export function relevanceStatus(settings: unknown, searchRerank: string | null | undefined): RelevanceStatus | null {
  const reranker = isRecord(settings) && isRecord(settings.reranker) ? settings.reranker : null;
  const classification = isRecord(settings) && isRecord(settings.data_classification) ? settings.data_classification : null;
  // This search's own state wins over the settings read before it.
  const state = typeof searchRerank === "string" && searchRerank
    ? searchRerank
    : typeof reranker?.state === "string" ? reranker.state : null;
  if (!state) return null;
  const effective = typeof classification?.effective === "string" && classification.effective ? classification.effective : null;
  const source = typeof classification?.source === "string" ? SOURCE_TEXT[classification.source] ?? null : null;
  const classificationText = classification
    ? `Data classification: ${effective ?? "not set"}${effective && source ? ` (${source})` : ""}.`
    : null;
  if (state === "ok") return { active: true, text: "Relevance ranking active.", classification: classificationText };
  const hold = typeof reranker?.hold_reason === "string" ? reranker.hold_reason : "";
  // A settings reason explains this state only when the settings report the same state.
  const reason = (reranker?.state === state && HOLD_TEXT[hold]) || STATE_TEXT[state] || `reranker state ${state}`;
  return { active: false, text: `Relevance ranking unavailable: ${reason}.`, classification: classificationText };
}

/**
 * Display-only, nothing is hidden or dropped: the server's floor (`min_relevance`) already left out what the reranker
 * judges irrelevant. When this search was reranked and every passage carries a relevance, the trailing passages below
 * this share of the best one are shown under "Less relevant".
 */
export const LESS_RELEVANT_SHARE = 0.5;

/** Where the "Less relevant" tail starts, or null when there is none to show (no scores, not reranked, no tail). */
export function lessRelevantStart(hits: { relevance?: number | null }[], rerank: string | null | undefined): number | null {
  if (rerank !== "ok" || hits.length < 2) return null;
  const scores = hits.map((hit) => hit.relevance);
  if (!scores.every((score): score is number => typeof score === "number" && Number.isFinite(score))) return null;
  const cutoff = Math.max(...scores) * LESS_RELEVANT_SHARE;
  let start = hits.length;
  while (start > 0 && scores[start - 1] < cutoff) start -= 1;
  return start > 0 && start < hits.length ? start : null;
}

// No relevance number is shown: the ranking is the order of the hits.

export const NO_MATCH_TEXT =
  "No matching knowledge found. Try another wording or other terms. This only means no source passage matched; it does not confirm or refute anything.";

// A refusal that is a state of the instance, not of the query, reads as that state with its next step (outsider
// walkthrough: "Workspace knowledge storage is not configured." stood in a red box with no way on).
// Knowledge storage is set in the deployment, not in the app, so the administrator's step names the deployment and
// links the install guide's section for it.
export type SearchRefusal = { title: string; text: string; link?: { href: string; label: string } };

export const KNOWLEDGE_STORAGE_GUIDE = "https://octryx.ai/docs/install/knowledge-storage#object-store";

export function searchRefusal(state: string | null | undefined, isAdmin: boolean): SearchRefusal | null {
  if (state === "needs_configuration") {
    return isAdmin ? {
      title: "Knowledge storage is not set up on this instance",
      text: "Search, uploads and syncs need the instance's object store. The Docker Compose install sets it up on "
        + "its first start; on another install, set it in the deployment's configuration and restart the server.",
      link: { href: KNOWLEDGE_STORAGE_GUIDE, label: "How to set up knowledge storage" },
    } : {
      title: "Knowledge search is not available yet",
      text: "Your administrator has not set up knowledge storage on this instance yet.",
    };
  }
  if (state === "unavailable") {
    return { title: "Knowledge storage is not reachable right now", text: "Try the search again in a moment." };
  }
  return null;
}
