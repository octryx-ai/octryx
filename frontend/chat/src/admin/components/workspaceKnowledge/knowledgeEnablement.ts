import { knowledgeBase } from "./workspaceKnowledgeRequest";

// Whether the Workspace's Knowledge is enabled, as the connectors panel shows it. Synced items are
// stored in the ledger either way, but search finds them only once Knowledge is enabled for the Workspace.
//
// Read from the server, never guessed:
// - the connectors listing's `knowledge: { state, outcome, checked_at }` (backend,
//   services/knowledge/projection/workspace_knowledge_state.py): the last recorded enablement, `unknown` when
//   none is recorded yet; configuring a connector and Run now enable Knowledge themselves. A listing without
//   `knowledge` makes the panel say it is not reported;
// - the answer of POST /knowledge/enable (`{ workspace_id, state, outcome }`, 200 ready, 503
//   needs_configuration; idempotent, Workspace authors only).

// `not_recorded` is the server's `unknown` (no enablement recorded); `not_reported`: the listing has no `knowledge`.
export type KnowledgeState =
  | "ready"
  | "needs_configuration"
  | "not_recorded"
  | "not_reported";

export type KnowledgeEnablement = {
  state: KnowledgeState;
  outcome: string | null;
  checkedAt: string | null;
};

const SERVER_STATES: Record<string, KnowledgeState> = {
  ready: "ready",
  needs_configuration: "needs_configuration",
  unknown: "not_recorded",
};
const OUTCOME = /^[a-z0-9_]{1,64}$/;

const isRecord = (value: unknown): value is Record<string, unknown> =>
  Boolean(value) && typeof value === "object" && !Array.isArray(value);

function parseState(value: unknown): KnowledgeEnablement | null {
  if (!isRecord(value) || typeof value.state !== "string") return null;
  const state = Object.prototype.hasOwnProperty.call(SERVER_STATES, value.state)
    ? SERVER_STATES[value.state]
    : null;
  if (!state) return null;
  const outcome =
    typeof value.outcome === "string" && OUTCOME.test(value.outcome)
      ? value.outcome
      : null;
  const checkedAt =
    typeof value.checked_at === "string" ? value.checked_at : null;
  return { state, outcome, checkedAt };
}

/** The Knowledge state the connectors listing reports; "not_reported" when it does not. */
export function knowledgeStateOf(listing: unknown): KnowledgeEnablement {
  return (
    (isRecord(listing) ? parseState(listing.knowledge) : null) ?? {
      state: "not_reported",
      outcome: null,
      checkedAt: null,
    }
  );
}

export function knowledgeStateText(state: KnowledgeState): string {
  // One sentence each; why and how is page help (help/knowledge/workspaceKnowledge.md).
  switch (state) {
    case "ready":
      return "Synced items are indexed for search.";
    case "not_recorded":
      return "Search cannot find synced items until Knowledge is enabled.";
    case "needs_configuration":
      return "Knowledge needs configuration by an operator before search can find synced items.";
    default:
      return "Synced items become searchable once Knowledge is enabled.";
  }
}

/** POST /knowledge/enable; the closed state is read also from a 503 answer. */
export async function enableKnowledge(
  workspaceId: string,
  fetcher: typeof fetch = fetch,
): Promise<KnowledgeEnablement> {
  const response = await fetcher(`${knowledgeBase(workspaceId)}/enable`, {
    method: "POST",
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (response.status === 403)
    throw new Error(
      "Enabling Knowledge needs the Workspace admin or owner role.",
    );
  const body: unknown = await response.json().catch(() => null);
  const parsed = parseState(body);
  if (parsed) return parsed;
  throw new Error(`Enabling Knowledge failed (${response.status}).`);
}
