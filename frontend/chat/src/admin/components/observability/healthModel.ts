// Observability → Health: one row per thing that can break; unknown and disabled are their own states.
import type { AdminTab } from "../../types/adminPanelTypes.governance";
import type { BadgeTone } from "./obUi";

export type HealthStatus = "ok" | "degraded" | "failing" | "unknown" | "disabled";
export type HealthLink = { tab?: AdminTab; href?: string; label: string } | null;
export type HealthRow = {
  component: string;
  status: HealthStatus;
  since: string | null;
  last_check: string | null;
  detail: string;
  link: HealthLink;
};
export type HealthGroup = { key: string; label: string; owner: string; rows: HealthRow[] };
export type HealthPayload = { checked_at: string; summary: Record<HealthStatus, number>; groups: HealthGroup[] };

export const HEALTH_BADGES: Record<HealthStatus, [BadgeTone, string]> = {
  ok: ["active", "✓ OK"],
  failing: ["danger", "✕ failing"],
  degraded: ["attention", "! degraded"],
  unknown: ["neutral", "? unknown"],
  disabled: ["neutral", "– disabled"],
};

/** The worst status of a group, for the Overview strip: failing > degraded > unknown > ok > disabled. */
export function worstStatus(rows: HealthRow[]): HealthStatus {
  for (const status of ["failing", "degraded", "unknown", "ok"] as HealthStatus[]) {
    if (rows.some((row) => row.status === status)) return status;
  }
  return rows.length ? "disabled" : "unknown";
}

export function countByStatus(rows: HealthRow[]): Partial<Record<HealthStatus, number>> {
  const counts: Partial<Record<HealthStatus, number>> = {};
  for (const row of rows) counts[row.status] = (counts[row.status] ?? 0) + 1;
  return counts;
}
