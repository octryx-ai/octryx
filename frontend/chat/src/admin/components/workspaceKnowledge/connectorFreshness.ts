import { apiTimeOf } from "./apiTime";
import { formatTime, intervalText } from "./connectorDisplay";
import { scheduleOf } from "./connectorConfig";
import type { RunReport, RunMode, SourceConnector, SyncCursor, SyncRun } from "./connectorTypes";

// How fresh a connector's knowledge is. Pure: no requests, no React.
//
// Read from the connectors listing, never guessed:
// - the last run and its counts: `last_run.report` (created → new, updated → changed, retired → removed);
// - withheld (restricted) items: the dedicated `report.withheld` count when the server sends it, else the
//   existing `report.skipped_reasons.restricted_acl` count, which is the same fail-closed withholding;
// - the next run: `schedule.next_run_at`;
// - whether this instance runs schedules at all: `instance_scheduler_enabled` on the listing (or
//   `schedule.instance_enabled` on the connector). When the answer carries neither, the page says so
//   instead of claiming either state.
//
// Corrections: server times are read as UTC; a completed run with failed or deferred
// items is "completed with failures", not a clean pass; the run's listing mode (`report.mode`) and the last
// clean full pass (`cursor.last_completed_at`, with `last_pass_closed_at`/`last_pass_failures` for a pass that
// did not count) are stated; the withheld explanation follows `report.withheld_reasons` and
// `report.acl_enforced`.

export type InstanceScheduler = "on" | "off" | "unknown";

export function instanceSchedulerState(
  listing: unknown,
  connector?: SourceConnector | null,
): InstanceScheduler {
  const own = (
    connector?.schedule as { instance_enabled?: unknown } | undefined
  )?.instance_enabled;
  if (typeof own === "boolean") return own ? "on" : "off";
  const listed =
    listing && typeof listing === "object"
      ? (listing as { instance_scheduler_enabled?: unknown })
          .instance_scheduler_enabled
      : undefined;
  if (typeof listed === "boolean") return listed ? "on" : "off";
  return "unknown";
}

const count = (value: unknown): number =>
  typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0;

export type PageCounts = {
  new: number;
  changed: number;
  removed: number;
  withheld: number;
};

export function runPageCounts(
  report: RunReport | null | undefined,
): PageCounts {
  const raw = (report ?? {}) as RunReport & { withheld?: unknown };
  const withheld =
    typeof raw.withheld === "number"
      ? count(raw.withheld)
      : count(raw.skipped_reasons?.restricted_acl);
  return {
    new: count(raw.created),
    changed: count(raw.updated),
    removed: count(raw.retired),
    withheld,
  };
}

/** What one synced item is called for this kind of source. */
export function itemNoun(kind: string, plural: boolean): string {
  const nouns: Record<string, [string, string]> = {
    confluence: ["page", "pages"],
    jira: ["issue", "issues"],
    servicenow: ["article or record", "articles and records"],
    git_repository: ["file", "files"],
  };
  const [one, many] = nouns[kind] ?? ["item", "items"];
  return plural ? many : one;
}

export function pageCountsText(kind: string, counts: PageCounts): string {
  return `${itemNoun(kind, true)}: ${counts.new} new · ${counts.changed} changed · ${counts.removed} removed · ${counts.withheld} withheld`;
}

function sourceName(kind: string): string {
  return kind === "confluence"
    ? "Confluence"
    : kind === "jira"
      ? "Jira"
      : "the source system";
}

/** Withheld items by reason: the dedicated `withheld_reasons`, else this run's skip reasons. */
export function withheldReasons(report: RunReport | null | undefined): {
  restricted: number;
  unresolved: number;
} {
  const reasons =
    report?.withheld_reasons && typeof report.withheld_reasons === "object"
      ? report.withheld_reasons
      : (report?.skipped_reasons ?? {});
  return {
    restricted: count(reasons.restricted_acl),
    unresolved: count(reasons.acl_unresolved),
  };
}

/** Why restricted items are missing, or null when none are withheld (the reason decides the text). */
export function withheldText(
  kind: string,
  report: RunReport | null | undefined,
): string | null {
  const withheld = runPageCounts(report).withheld;
  if (withheld <= 0) return null;
  const noun = itemNoun(kind, withheld !== 1);
  const source = sourceName(kind);
  const enforced =
    typeof report?.acl_enforced === "boolean" ? report.acl_enforced : null;
  const reasons = withheldReasons(report);
  const they = withheld === 1 ? "it is" : "they are";
  if (enforced === false) {
    return `${withheld} restricted ${noun} withheld. This Workspace does not enforce ${source} permissions, so restricted ${itemNoun(kind, true)} are not indexed. Open them in ${source} directly.`;
  }
  if (enforced === true || (reasons.unresolved > 0 && !reasons.restricted)) {
    return `${withheld} restricted ${noun} not indexed: ${they} restricted in ${source} to people this Workspace cannot match to its members, so ${they} withheld instead of being shown to everyone. Open them in ${source} directly.`;
  }
  // Neither the reason split nor the Workspace's enforcement is known: say only what is known.
  return `${withheld} restricted ${noun} not indexed: ${they} restricted in ${source}, so ${they} withheld instead of being shown to everyone. Open them in ${source} directly.`;
}

/** Failed and deferred items of a run: either keeps a pass from counting as a clean reconciliation. */
export function runFailures(report: RunReport | null | undefined): {
  failed: number;
  deferred: number;
} {
  return { failed: count(report?.failed), deferred: count(report?.deferred) };
}

/** A run that completed but left failed or deferred items: shown as a warning, never as a clean pass. */
export function completedWithFailures(
  run: Pick<SyncRun, "state" | "report"> | null | undefined,
): boolean {
  if (!run || run.state !== "completed") return false;
  const { failed, deferred } = runFailures(run.report);
  return failed + deferred > 0;
}

function failuresText(kind: string, failed: number, deferred: number): string {
  const parts = [
    failed ? `${failed} failed` : "",
    deferred ? `${deferred} deferred` : "",
  ].filter(Boolean);
  return `${parts.join(" and ")} ${itemNoun(kind, failed + deferred !== 1)}`;
}

/** The "Sync now" result line, from the run's state and report. */
export function runResultText(
  run: Pick<SyncRun, "state" | "report">,
  kind = "",
): string {
  if (completedWithFailures(run)) {
    const { failed, deferred } = runFailures(run.report);
    return `The run completed with ${failuresText(kind, failed, deferred)}: it does not count as a full pass, and they are retried on the next run.`;
  }
  const fixed: Record<string, string> = {
    completed: "The run completed a full pass.",
    budget_exhausted:
      "The run reached its item budget; run again to continue the pass.",
    failed: "The run stopped early; the cursor stays where it was.",
    needs_configuration: "The run could not start.",
  };
  return fixed[run.state] ?? `The run ended as ${run.state}.`;
}

/** How the last run listed the source; null when the server does not report it. */
export function runModeText(
  kind: string,
  report: RunReport | null | undefined,
): string | null {
  const mode = report?.mode as RunMode | undefined;
  const all = itemNoun(kind, true);
  const text: Record<RunMode, string> = {
    full: `Full pass: listed every ${itemNoun(kind, false)} in scope`,
    incremental: `Incremental: changed ${all} first, then a listing of the scope`,
    incremental_fallback:
      "Full listing: the change query failed, so the run listed the whole scope",
  };
  if (!mode || !(mode in text)) return null;
  return report?.pass_completed === false
    ? `${text[mode]} (listing not finished; the next run continues it)`
    : text[mode];
}

/** When the last clean full pass completed, and why a later pass did not count. */
export function lastFullPassText(
  kind: string,
  cursor: SyncCursor | null | undefined,
): string {
  const clean =
    cursor?.last_completed_at && apiTimeOf(cursor.last_completed_at) !== null
      ? formatTime(cursor.last_completed_at)
      : null;
  const base = clean ?? "No full pass has completed yet.";
  const closed = apiTimeOf(cursor?.last_pass_closed_at);
  const failures = count(cursor?.last_pass_failures);
  const later =
    closed !== null &&
    failures > 0 &&
    (clean === null || closed > (apiTimeOf(cursor?.last_completed_at) ?? 0));
  if (!later) return base;
  return `${base} The pass that closed ${formatTime(cursor?.last_pass_closed_at)} had ${failures} failed or deferred ${itemNoun(kind, failures !== 1)}, so it does not count; they are retried on the next run.`;
}

export function runNowText(kind: string): string {
  return `Sync now performs a full pass: it lists every ${itemNoun(kind, false)} in scope, retires those deleted or moved at the source and re-checks permissions (in steps when the scope exceeds the per-run limit).`;
}

/** The next scheduled run, stated with the instance switch and the pause state. */
export function nextRunText(
  connector: SourceConnector,
  instance: InstanceScheduler,
  now = Date.now(),
): string {
  const schedule = scheduleOf(connector);
  if (connector.state === "paused")
    return "No scheduled syncs while the source is paused; Sync now works again after resuming.";
  if (!schedule.enabled)
    return "Not scheduled: it syncs only when someone uses Sync now.";
  const every = `Every ${intervalText(schedule.interval_minutes)}`;
  if (instance === "off") {
    return `${every} is set, but scheduled runs are switched off for this instance, so nothing runs on a schedule. Only Sync now syncs.`;
  }
  // Next_run_at is UTC; an unreadable value is said as such, never as "due now".
  const at = apiTimeOf(schedule.next_run_at);
  const next = !schedule.next_run_at
    ? "next run due now"
    : at === null
      ? "next run time not readable"
      : at <= now
        ? "next run due now"
        : `next run ${formatTime(schedule.next_run_at)}`;
  return instance === "on"
    ? `${every}; ${next}.`
    : `${every}; ${next}.`;
}

// Knowledge that nothing keeps current is out of date after this long: the same threshold as the Problems page's
// `stale` finding (backend `services/problems/syncs.py`, STALE_AFTER), so the page and Problems agree.
export const STALE_AFTER_DAYS = 14;
const DAY_MS = 24 * 60 * 60 * 1000;

/** Whether a source last synced at `at` is older than STALE_AFTER_DAYS; false when it never synced. */
export function syncIsStale(at: number | null, now = Date.now()): boolean {
  return at !== null && now - at > STALE_AFTER_DAYS * DAY_MS;
}

/** "Synced today", "Synced 1 day ago", "Synced 31 days ago": the age in whole days, never a bare "Synced". */
export function syncAgeText(at: number, now = Date.now()): string {
  const days = Math.max(0, Math.floor((now - at) / DAY_MS));
  return days === 0 ? "Synced today" : `Synced ${days} day${days === 1 ? "" : "s"} ago`;
}

export function instanceSchedulerText(instance: InstanceScheduler): string {
  if (instance === "on")
    return "Scheduled runs are switched on for this instance.";
  if (instance === "off") {
    return "Automatic sync is off on this instance; only Sync now syncs until an operator switches it on.";
  }
  return "";
}
