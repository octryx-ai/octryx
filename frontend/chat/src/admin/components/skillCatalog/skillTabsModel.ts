import { usageSplit } from "./skillCatalogModel";
import type { SkillRow } from "./skillCatalogTypes";
import type { SourceRow, UsageSummary } from "./skillDeliveryTypes";
import { formatDateTime } from "../../utils/dateTime";

// Pure helpers of the Categories, Sources & updates and Usage tabs: resulting category keys, source rows
// joined with the catalog rows, check intervals and the usage KPIs.

/** Mirrors the server: a short key under a parent becomes `<parent key>.<key>`. */
export function resultingKey(parentKey: string | null, raw: string): string {
  const key = raw.trim().toLowerCase();
  if (!parentKey || !key || key.includes(".")) return key;
  return `${parentKey}.${key}`;
}

export function workspacesLabel(count: number | undefined): string {
  if (!count) return "—";
  return `${count} Workspace${count === 1 ? "" : "s"}`;
}

export function serverTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return formatDateTime(iso, iso);
}

export const csv = (text: string): string[] => text.split(",").map((item) => item.trim()).filter(Boolean);

export const INTERVALS: { hours: number; label: string }[] = [
  { hours: 0, label: "Manual only" },
  { hours: 6, label: "Every 6 hours" },
  { hours: 24, label: "Daily" },
  { hours: 168, label: "Weekly" },
];

/** The interval options, plus the stored value when it is none of them. */
export function intervalOptions(current: number): { hours: number; label: string }[] {
  if (INTERVALS.some((option) => option.hours === current)) return INTERVALS;
  return [...INTERVALS, { hours: current, label: `Every ${current} hours` }];
}

export const TRUST_CHOICES = [
  { value: "official", label: "Official" },
  { value: "community", label: "Community" },
  { value: "internal", label: "Internal" },
];

export function trustBadge(trust: string): { label: string; className: string } {
  const label = TRUST_CHOICES.find((choice) => choice.value === trust)?.label ?? "Community";
  return { label, className: `work-badge work-badge--${trust === "community" ? "neutral" : "running"}` };
}

export const isUploadRow = (row: SkillRow) => !row.source || row.source.kind === "upload";
export const sourceRows = (rows: SkillRow[], source: SourceRow) => rows.filter((row) => row.source?.id === source.id);

export function trackingLabel(rows: SkillRow[]): string {
  const follow = rows.filter((row) => row.tracking_mode === "follow").length;
  const pinned = rows.filter((row) => row.tracking_mode === "pinned").length;
  if (!follow && !pinned) return "—";
  if (!pinned) return "Follow upstream";
  if (!follow) return "Pinned";
  return `${follow} follow upstream · ${pinned} pinned`;
}

type CheckAll = { sources?: number; skills?: number; updates?: number; drafts?: number; errors?: number };
type CheckOne = { results?: { name?: string; update_available?: boolean; error?: string | null }[] };

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

export function checkAllText(raw: unknown): string {
  const value = (raw ?? {}) as CheckAll;
  return `Checked ${plural(value.sources ?? 0, "source")}: ${plural(value.skills ?? 0, "skill")}, `
    + `${plural(value.updates ?? 0, "update")}, ${plural(value.drafts ?? 0, "draft")} created, ${plural(value.errors ?? 0, "error")}.`;
}

export function checkOneText(label: string, raw: unknown): string {
  const results = ((raw ?? {}) as CheckOne).results ?? [];
  const updates = results.filter((item) => item.update_available).length;
  const errors = results.filter((item) => item.error).length;
  return `Checked ${label}: ${plural(results.length, "skill")}, ${plural(updates, "update")}, ${plural(errors, "error")}.`;
}

export const DAY_CHOICES = [7, 30, 90];

export function usageKpis(usage: UsageSummary, rows: SkillRow[]) {
  let chat = 0;
  let octryx = 0;
  for (const entry of usage.skills) {
    const split = usageSplit(entry.by_surface);
    chat += split.chat;
    octryx += split.model + split.slash;
  }
  const published = rows.filter((row) => row.published).length;
  const inUse = usage.skills.filter((entry) => entry.uses > 0).length;
  return { chat, octryx, published, inUse, unused: Math.max(0, published - inUse) };
}
