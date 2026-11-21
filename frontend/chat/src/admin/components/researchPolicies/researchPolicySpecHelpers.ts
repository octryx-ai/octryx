export type ResearchPolicySpec = Record<string, unknown>;

export function asRecord(value: unknown): ResearchPolicySpec {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as ResearchPolicySpec)
    : {};
}

export function asString(value: unknown, fallback = "") {
  return typeof value === "string" ? value : fallback;
}

export function asNumber(value: unknown, fallback = 0) {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim()) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return fallback;
}

export function asBoolean(value: unknown, fallback = false) {
  return typeof value === "boolean" ? value : fallback;
}

export function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || "").trim()).filter(Boolean);
}

export function listToText(value: unknown) {
  return asStringArray(value).join("\n");
}

export function textToList(value: string) {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function parsePolicySpecDraft(value: string): ResearchPolicySpec {
  const parsed = JSON.parse(value) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("Research policy spec must be a JSON object.");
  }
  return parsed as ResearchPolicySpec;
}

export function formatPolicySpec(spec: ResearchPolicySpec) {
  return JSON.stringify(spec || {}, null, 2);
}

export function updateSpecPath(
  spec: ResearchPolicySpec,
  path: string[],
  value: unknown,
): ResearchPolicySpec {
  const next = JSON.parse(JSON.stringify(spec || {})) as ResearchPolicySpec;
  let cursor: ResearchPolicySpec = next;
  for (const segment of path.slice(0, -1)) {
    const current = cursor[segment];
    if (!current || typeof current !== "object" || Array.isArray(current)) {
      cursor[segment] = {};
    }
    cursor = cursor[segment] as ResearchPolicySpec;
  }
  cursor[path[path.length - 1]] = value;
  return next;
}

export function getSpecPath(spec: ResearchPolicySpec, path: string[]): unknown {
  let current: unknown = spec;
  for (const segment of path) {
    if (!current || typeof current !== "object" || Array.isArray(current))
      return undefined;
    current = (current as ResearchPolicySpec)[segment];
  }
  return current;
}

export function numberAt(
  spec: ResearchPolicySpec,
  path: string[],
  fallback = 0,
) {
  return asNumber(getSpecPath(spec, path), fallback);
}

export function stringAt(
  spec: ResearchPolicySpec,
  path: string[],
  fallback = "",
) {
  return asString(getSpecPath(spec, path), fallback);
}

export function booleanAt(
  spec: ResearchPolicySpec,
  path: string[],
  fallback = false,
) {
  return asBoolean(getSpecPath(spec, path), fallback);
}
