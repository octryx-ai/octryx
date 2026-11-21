// Pure model of the admin private-host egress allowlist (#S6).
// Contract: backend/app/web/routers/panel_egress.py and
// backend/app/services/outbound_egress/private_hosts.py. The server is authoritative;
// the client check here only catches obvious shape errors before a round trip.
// Only fixed reason codes are ever shown; server free text never reaches the UI.

export const MAX_PRIVATE_HOST_ENTRIES = 50;

export type PrivateHostRow = {
  key: string;
  value: string;
  refusal: string | null;
};

export type PrivateHostDraft = {
  connection: string;
  saved: string[];
  rows: PrivateHostRow[];
  listRefusal: string | null;
  dirty: boolean;
};

export type PrivateHostRefusal = {
  reason: string;
  entryIndex: number | null;
};

const REASON_CODE = /^[a-z][a-z0-9_]{0,63}$/;
const CONNECTION_NAME = /^[a-z][a-z0-9_]{0,63}$/;
const BRACKETED = /^\[([0-9a-f:.]+)\]:(\d{1,5})$/;
const PLAIN = /^([^:[\]\s]+):(\d{1,5})$/;
const FALLBACK_REASON = "request_refused";

const CONNECTION_LABELS: Record<string, string> = {
  azure_devops: "Azure DevOps Server",
  bitbucket: "Bitbucket",
  confluence: "Confluence",
  github: "GitHub",
  gitlab: "GitLab",
  jira: "Jira",
  outbound_webhook: "Outbound webhooks",
  servicenow: "ServiceNow",
  sonarqube: "SonarQube Server",
};

export function connectionLabel(connection: string): string {
  return CONNECTION_LABELS[connection] ?? connection;
}

/** A fixed reason code, or a neutral fallback when the value is not a plain code. */
export function safeReasonCode(value: unknown): string {
  return typeof value === "string" && REASON_CODE.test(value)
    ? value
    : FALLBACK_REASON;
}

export function normalizeEntryInput(raw: string): string {
  return raw.trim().toLowerCase();
}

/** Client-side shape check with the server's reason codes; null when the shape is fine. */
export function entryShapeRefusal(entry: string): string | null {
  if (!entry) return "entry_malformed";
  const match = BRACKETED.exec(entry) ?? PLAIN.exec(entry);
  if (!match) {
    return entry.includes(":") ? "entry_malformed" : "entry_port_required";
  }
  const port = Number(match[2]);
  return port >= 1 && port <= 65535 ? null : "entry_malformed";
}

let rowSequence = 0;

function newRow(value: string): PrivateHostRow {
  rowSequence += 1;
  return { key: `row-${rowSequence}`, value, refusal: null };
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

export function draftFromEntries(
  connection: string,
  entries: string[],
): PrivateHostDraft {
  return {
    connection,
    saved: [...entries],
    rows: entries.map(newRow),
    listRefusal: null,
    dirty: false,
  };
}

/** The GET body as drafts, in the server's allowlistable order; unknown shapes are dropped. */
export function draftsFromPayload(payload: unknown): PrivateHostDraft[] {
  if (!payload || typeof payload !== "object") return [];
  const body = payload as { allowlistable?: unknown; connections?: unknown };
  const connections =
    body.connections && typeof body.connections === "object"
      ? (body.connections as Record<string, unknown>)
      : {};
  return stringList(body.allowlistable)
    .filter((name) => CONNECTION_NAME.test(name))
    .map((name) => draftFromEntries(name, stringList(connections[name])));
}

export function entriesOf(draft: PrivateHostDraft): string[] {
  return draft.rows.map((row) => row.value);
}

export type AddEntryResult =
  | { ok: true; draft: PrivateHostDraft }
  | { ok: false; reason: string };

export function addEntry(draft: PrivateHostDraft, raw: string): AddEntryResult {
  const entry = normalizeEntryInput(raw);
  const shapeRefusal = entryShapeRefusal(entry);
  if (shapeRefusal) return { ok: false, reason: shapeRefusal };
  if (draft.rows.some((row) => row.value === entry)) {
    return { ok: false, reason: "entry_duplicate" };
  }
  if (draft.rows.length >= MAX_PRIVATE_HOST_ENTRIES) {
    return { ok: false, reason: "too_many_entries" };
  }
  return {
    ok: true,
    draft: {
      ...draft,
      rows: [...draft.rows, newRow(entry)],
      listRefusal: null,
      dirty: true,
    },
  };
}

export function removeEntry(
  draft: PrivateHostDraft,
  rowKey: string,
): PrivateHostDraft {
  return {
    ...draft,
    rows: draft.rows.filter((row) => row.key !== rowKey),
    listRefusal: null,
    dirty: true,
  };
}

/** Marks the refused entry (by index of the list that was sent) and keeps the draft editable. */
export function applyRefusal(
  draft: PrivateHostDraft,
  refusal: PrivateHostRefusal,
): PrivateHostDraft {
  const index = refusal.entryIndex;
  const hasRow = index !== null && index >= 0 && index < draft.rows.length;
  return {
    ...draft,
    rows: draft.rows.map((row, position) => ({
      ...row,
      refusal: hasRow && position === index ? refusal.reason : null,
    })),
    listRefusal: hasRow ? null : refusal.reason,
  };
}

/** The 400 refusal body of the PUT, or null for anything else. */
export function parsePrivateHostRefusal(
  status: number,
  payload: unknown,
): PrivateHostRefusal | null {
  if (status !== 400 || !payload || typeof payload !== "object") return null;
  const detail = (payload as { detail?: unknown }).detail;
  if (!detail || typeof detail !== "object") return null;
  const body = detail as {
    state?: unknown;
    reason?: unknown;
    entry_index?: unknown;
  };
  if (body.state !== "private_host_entry_refused") return null;
  const index = body.entry_index;
  return {
    reason: safeReasonCode(body.reason),
    entryIndex:
      typeof index === "number" && Number.isInteger(index) && index >= 0
        ? index
        : null,
  };
}

/** The fixed state code of a failed GET (409 allowlist unavailable), else an HTTP code. */
export function loadFailureCode(status: number, payload: unknown): string {
  const detail =
    payload && typeof payload === "object"
      ? (payload as { detail?: unknown }).detail
      : null;
  const state =
    detail && typeof detail === "object"
      ? (detail as { state?: unknown }).state
      : null;
  if (typeof state === "string" && REASON_CODE.test(state)) return state;
  return `http_${Number.isInteger(status) ? status : 0}`;
}

/**
 * Which connection types get an allowlist form: a type with a
 * configured connector, a type that already has saved or unsaved entries, or
 * one the admin opened through "Add on-prem host". The rest stay hidden but
 * reachable; nothing about the stored allowlist changes.
 */
export function partitionAllowlistDrafts(
  drafts: ReadonlyArray<PrivateHostDraft>,
  configuredConnectors: ReadonlyArray<string>,
  opened: ReadonlyArray<string>,
): { shown: PrivateHostDraft[]; hidden: PrivateHostDraft[] } {
  const configured = new Set(configuredConnectors);
  const revealed = new Set(opened);
  const shown: PrivateHostDraft[] = [];
  const hidden: PrivateHostDraft[] = [];
  for (const draft of drafts) {
    const visible =
      configured.has(draft.connection) ||
      revealed.has(draft.connection) ||
      draft.saved.length > 0 ||
      draft.rows.length > 0 ||
      draft.dirty;
    (visible ? shown : hidden).push(draft);
  }
  return { shown, hidden };
}

// A refused entry reads as a sentence, never as the server's reason code.
const REFUSAL_SENTENCES: Record<string, string> = {
  entry_malformed: "Not a host:port entry.",
  entry_port_required: "Add the port, for instance :443.",
  entry_pod_local_refused: "Pod-local and metadata addresses are never allowed.",
  entry_not_private: "This is a public address; only private hosts need to be listed.",
};

export function refusalSentence(code: string | null | undefined): string {
  return REFUSAL_SENTENCES[String(code || "")] ?? "The server refused this entry.";
}
