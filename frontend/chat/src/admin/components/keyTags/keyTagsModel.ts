// Scope keys as tags (delivery 5): one key per tag instead of a JSON or comma text field.
//
// The tag input is generic (Confluence spaces, a named connection's bound keys, Workspace limits). Keys are
// compared case-insensitively; `canonical` decides how a typed key is stored (e.g. upper-cased binding keys).
// Confluence's `confluence_allowed_spaces` keeps its stored shape `[{space_key, enabled, ...}]`: the tags are the
// enabled keys, every other entry and property (labels, disabled entries) is kept as stored.

export type KeyRule = {
  // A full-match pattern (the descriptor binding pattern or a connector key rule); empty: any non-blank key.
  pattern?: string;
  canonical?: (key: string) => string;
};

const SEPARATORS = /[\s,;]+/;

function same(left: string, right: string): boolean {
  return left.toLowerCase() === right.toLowerCase();
}

/** The keys of a typed or pasted text, canonical and without duplicates (case-insensitive). */
export function splitKeys(text: string, rule: KeyRule = {}): string[] {
  const keys: string[] = [];
  for (const raw of text.split(SEPARATORS)) {
    const key = (rule.canonical ?? ((value: string) => value))(raw.trim());
    if (key && !keys.some((known) => same(known, key))) keys.push(key);
  }
  return keys;
}

/** The keys of `text` that do not match the rule's pattern. */
export function invalidKeys(keys: string[], rule: KeyRule = {}): string[] {
  if (!rule.pattern) return [];
  const pattern = new RegExp(`^(?:${rule.pattern})$`);
  return keys.filter((key) => !pattern.test(key));
}

/** `current` plus the valid keys of `text`; the invalid ones are returned so the input can keep and name them. */
export function addKeys(current: string[], text: string, rule: KeyRule = {}): { keys: string[]; invalid: string[] } {
  const typed = splitKeys(text, rule);
  const invalid = invalidKeys(typed, rule);
  const keys = [...current];
  for (const key of typed) {
    if (!invalid.includes(key) && !keys.some((known) => same(known, key))) keys.push(key);
  }
  return { keys, invalid };
}

export function removeKey(current: string[], key: string): string[] {
  return current.filter((known) => !same(known, key));
}

// ---------------------------------------------------------------------------
// confluence_allowed_spaces: [{space_key, enabled}] <-> tags
// ---------------------------------------------------------------------------

type SpaceEntry = Record<string, unknown>;

export type SpaceTags = {
  // The enabled space keys (the tags).
  keys: string[];
  // Stored entries that are not tags (disabled ones), kept unchanged on save.
  disabled: string[];
  // The draft is not a list (hand-edited JSON): the tags cannot show it, the Advanced editor can.
  unreadable: boolean;
};

function entryKey(entry: unknown): string {
  if (typeof entry === "string") return entry.trim();
  if (!entry || typeof entry !== "object") return "";
  const value = (entry as SpaceEntry).space_key ?? (entry as SpaceEntry).key;
  return typeof value === "string" ? value.trim() : "";
}

function parsedSpaces(draftValue: string | undefined): unknown[] | null {
  const text = (draftValue ?? "").trim();
  if (!text) return [];
  try {
    const value = JSON.parse(text);
    return Array.isArray(value) ? value : null;
  } catch {
    return null;
  }
}

function enabled(entry: unknown): boolean {
  return typeof entry === "string" || (entry as SpaceEntry).enabled !== false;
}

export function spaceTags(draftValue: string | undefined): SpaceTags {
  const entries = parsedSpaces(draftValue);
  if (entries === null) return { keys: [], disabled: [], unreadable: true };
  const keys: string[] = [];
  const disabled: string[] = [];
  for (const entry of entries) {
    const key = entryKey(entry);
    if (!key) continue;
    (enabled(entry) ? keys : disabled).push(key);
  }
  return { keys, disabled, unreadable: false };
}

/**
 * The draft JSON for `keys`: a stored entry of a key keeps its properties (enabled again if it was disabled), a new
 * key gets `{space_key, enabled: true}`, and stored disabled entries of other keys stay as they were.
 */
export function spacesDraft(draftValue: string | undefined, keys: string[]): string {
  const entries = parsedSpaces(draftValue) ?? [];
  const next: unknown[] = [];
  for (const key of keys) {
    const stored = entries.find((entry) => same(entryKey(entry), key));
    next.push(stored && typeof stored === "object" ? { ...(stored as SpaceEntry), enabled: true } : { space_key: key, enabled: true });
  }
  for (const entry of entries) {
    const key = entryKey(entry);
    if (key && !enabled(entry) && !keys.some((known) => same(known, key))) next.push(entry);
  }
  return JSON.stringify(next, null, 2);
}
