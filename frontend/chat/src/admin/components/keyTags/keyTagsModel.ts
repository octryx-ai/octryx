// `confluence_allowed_spaces` keeps its stored shape: disabled entries and other properties stay as stored.

export type KeyRule = {
  pattern?: string;
  canonical?: (key: string) => string;
};

const SEPARATORS = /[\s,;]+/;

function same(left: string, right: string): boolean {
  return left.toLowerCase() === right.toLowerCase();
}

export function splitKeys(text: string, rule: KeyRule = {}): string[] {
  const keys: string[] = [];
  for (const raw of text.split(SEPARATORS)) {
    const key = (rule.canonical ?? ((value: string) => value))(raw.trim());
    if (key && !keys.some((known) => same(known, key))) keys.push(key);
  }
  return keys;
}

export function invalidKeys(keys: string[], rule: KeyRule = {}): string[] {
  if (!rule.pattern) return [];
  const pattern = new RegExp(`^(?:${rule.pattern})$`);
  return keys.filter((key) => !pattern.test(key));
}

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

type SpaceEntry = Record<string, unknown>;

export type SpaceTags = {
  keys: string[];
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
