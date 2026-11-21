import type { WorkItem } from "./workItemTypes";

// Plain readers of a Work Item's source fields for the detail.

export type DetailRecord = Record<string, unknown>;

export const FUTURE_SECTIONS = [
  { key: "execution_runs", title: "Execution runs" },
  { key: "validation_results", title: "Validation and policy gates" },
];

export function isRecord(value: unknown): value is DetailRecord {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function stringifyValue(value: unknown): string {
  if (value == null || value === "") return "-";
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(stringifyValue).filter((entry) => entry !== "-").join(", ") || "-";
  }
  if (isRecord(value)) {
    const preferred = value.name ?? value.displayName ?? value.display_name ?? value.key ?? value.id;
    return preferred != null ? stringifyValue(preferred) : JSON.stringify(value);
  }
  return String(value);
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

export function sourceRaw(item: WorkItem): DetailRecord {
  const sourceFields = item.source_fields || {};
  return isRecord(sourceFields.raw) ? sourceFields.raw : {};
}

export function rawFields(item: WorkItem): DetailRecord {
  const raw = sourceRaw(item);
  return isRecord(raw.fields) ? raw.fields : {};
}

export function firstString(...values: unknown[]): string {
  for (const value of values) {
    const text = stringifyValue(value);
    if (text && text !== "-") return text;
  }
  return "-";
}

export function optionalSourceObject(item: WorkItem, key: string): unknown {
  const fields = item.source_fields || {};
  return fields[key] ?? fields[`octryx_${key}`];
}

export function hasDetailValue(value: unknown): boolean {
  if (Array.isArray(value)) return value.length > 0;
  if (isRecord(value)) return Object.keys(value).length > 0;
  return Boolean(value);
}

export function isHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}
