// Governed policy lists: code-owned seeds, admin-edited live values.
// Every write creates the next version (e.g. `diagnosis.v2`) with an audit entry;
// a refused write answers with a closed `{code, values, message}` detail.

export const POLICY_LISTS_PATH = "/admin/chat/api/panel/policy-lists";

export const POLICY_LIST_REFUSAL_CODES = [
  "invalid_payload",
  "invalid_entry",
  "duplicate_entry",
  "empty_list",
  "unknown_tool",
  "required_tool_missing",
  "unknown_capability",
  "capability_in_use",
  "diagram_type_not_renderable",
  "out_of_range",
  "version_conflict",
  "unknown_policy_list",
] as const;

export type PolicyListRefusalCode = (typeof POLICY_LIST_REFUSAL_CODES)[number];

export type PolicyListRefusal = {
  code: PolicyListRefusalCode;
  values: string[];
  message: string;
};

export type PolicyListHistoryEntry = {
  key: string;
  action: string;
  at: string;
};

export type PolicyListState = {
  listId: string;
  key: string;
  version: number;
  seedKey: string;
  origin: string;
  recordState: string;
  matchesSeed: boolean;
  title: string;
  description: string;
  values: unknown[];
  // A settings record's values are one object (e.g. workflow_proposal_settings).
  settings: Record<string, unknown> | null;
  pinned: string[];
  history: PolicyListHistoryEntry[];
};

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

export function asText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function asNames(value: unknown): string[] {
  return Array.isArray(value)
    ? value.map(asText).filter((name) => name.length > 0)
    : [];
}

export function parseHistory(value: unknown): PolicyListHistoryEntry[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      const record = asRecord(item);
      return {
        key: asText(record.key),
        action: asText(record.action),
        at: asText(record.at),
      };
    })
    .filter((entry) => entry.key && entry.action);
}

/** One list's state; `null` when the payload lacks its identity. */
export function parsePolicyListState(value: unknown): PolicyListState | null {
  const record = asRecord(value);
  const listId = asText(record.list_id);
  const key = asText(record.key);
  const version = Number(record.version);
  if (!listId || !key || !Number.isInteger(version) || version < 1) return null;
  return {
    listId,
    key,
    version,
    seedKey: asText(record.seed_key),
    origin: asText(record.origin),
    recordState: asText(record.record_state),
    matchesSeed: record.matches_seed === true,
    title: asText(record.title) || listId,
    description: asText(record.description),
    values: Array.isArray(record.values) ? record.values : [],
    settings:
      record.values &&
      typeof record.values === "object" &&
      !Array.isArray(record.values)
        ? (record.values as Record<string, unknown>)
        : null,
    pinned: asNames(record.pinned),
    history: parseHistory(record.history),
  };
}

export function parsePolicyLists(payload: unknown): PolicyListState[] {
  const lists = asRecord(payload).lists;
  return Array.isArray(lists)
    ? lists
        .map(parsePolicyListState)
        .filter((state): state is PolicyListState => state !== null)
    : [];
}

/** The closed refusal of a failed write, or `null` when the answer is not one. */
export function parsePolicyListRefusal(
  payload: unknown,
): PolicyListRefusal | null {
  const detail = asRecord(asRecord(payload).detail);
  const code = asText(detail.code);
  if (!(POLICY_LIST_REFUSAL_CODES as readonly string[]).includes(code))
    return null;
  return {
    code: code as PolicyListRefusalCode,
    values: asNames(detail.values),
    message: asText(detail.message),
  };
}

export function refusalText(refusal: PolicyListRefusal): string {
  const values = refusal.values.length ? ` (${refusal.values.join(", ")})` : "";
  return `${refusal.code}${values}: ${refusal.message}`;
}

// ── Text codecs: the editors are plain text, one entry per line ─────────────

/** `name` per line → names (blank lines dropped). */
export function textToNames(text: string): string[] {
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

/** `key: label` per line → entries keyed by `keyField`. */
export function textToLabelled(
  text: string,
  keyField: "key" | "type",
): Record<string, string>[] {
  return textToNames(text).map((line) => {
    const separator = line.indexOf(":");
    const key = (separator < 0 ? line : line.slice(0, separator)).trim();
    const label = separator < 0 ? "" : line.slice(separator + 1).trim();
    return { [keyField]: key, label };
  });
}

export function labelledToText(
  values: unknown[],
  keyField: "key" | "type",
): string {
  return values
    .map((value) => {
      const record = asRecord(value);
      return `${asText(record[keyField])}: ${asText(record.label)}`;
    })
    .join("\n");
}

/** `family: tool, tool` per line → families in declared order. */
export function textToFamilies(
  text: string,
): { name: string; tools: string[] }[] {
  return textToNames(text).map((line) => {
    const separator = line.indexOf(":");
    const name = (separator < 0 ? line : line.slice(0, separator)).trim();
    const tools = separator < 0 ? [] : line.slice(separator + 1).split(",");
    return { name, tools: tools.map((tool) => tool.trim()).filter(Boolean) };
  });
}

export function familiesToText(
  families: { name: string; tools: string[] }[],
): string {
  return families
    .map((family) => `${family.name}: ${family.tools.join(", ")}`)
    .join("\n");
}

/** A settings object → `field: value` per line. */
export function settingsToText(
  settings: Record<string, unknown> | null,
): string {
  return Object.entries(settings ?? {})
    .map(([field, value]) => `${field}: ${String(value)}`)
    .join("\n");
}

/** `field: value` per line → a settings object; whole numbers become numbers. */
export function textToSettings(text: string): Record<string, unknown> {
  const settings: Record<string, unknown> = {};
  for (const line of textToNames(text)) {
    const separator = line.indexOf(":");
    if (separator < 0) continue;
    const field = line.slice(0, separator).trim();
    const value = line.slice(separator + 1).trim();
    settings[field] = /^-?\d+$/.test(value) ? Number(value) : value;
  }
  return settings;
}

export type PolicyListWriteResult =
  | { ok: true; state: PolicyListState | null }
  | { ok: false; refusal: PolicyListRefusal | null; status: number };

/** PUT an edit or POST a reset; a refusal keeps its closed code. */
export async function writePolicyList(
  path: string,
  method: "PUT" | "POST",
  body?: unknown,
): Promise<PolicyListWriteResult> {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: {
      Accept: "application/json",
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }
  if (!response.ok)
    return {
      ok: false,
      refusal: parsePolicyListRefusal(payload),
      status: response.status,
    };
  return { ok: true, state: parsePolicyListState(payload) };
}
