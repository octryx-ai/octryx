// Cedar policy engine model: modes and labels, the engine status, enforce readiness and outcome totals.
import { isRecord, num, optNum, str, strs } from "./policyEngineValues";

/** A server timestamp: naive ISO strings from the backend are UTC (`utc_now()`), not browser-local time. */
export function serverDate(iso: string): Date {
  const value = /(?:[zZ]|[+-]\d\d:?\d\d)$/.test(iso) ? iso : `${iso}Z`;
  return new Date(value);
}

export type PolicyMode = "off" | "shadow" | "enforce";
export const MODES: PolicyMode[] = ["off", "shadow", "enforce"];
export const MODE_LABELS: Record<PolicyMode, string> = {
  off: "Off — Cedar is not evaluated",
  shadow: "Shadow — Cedar is evaluated and compared, the existing checks decide",
  enforce: "Enforce — Cedar decides; the existing checks are the fallback when Cedar is unavailable",
};

export const POINT_LABELS: Record<string, string> = {
  seat: "Seat sessions",
  model_admission: "Company model admission",
  remote_model: "Reranker / remote embeddings",
  tool_admission: "Chat and MCP tool admission",
  gateway_tool_check: "octryx-claude tool check",
};
export const OUTCOME_LABELS: Record<string, string> = {
  match: "Agrees",
  mismatch: "Disagrees",
  custom_policy: "Custom policy denies",
  error: "Error (denied)",
  enforced: "Enforced denial",
  dropped: "Records dropped",
};
export const STATE_LABELS: Record<string, string> = {
  draft: "Draft",
  in_review: "In review",
  published: "Published",
  retired: "Retired",
};

export type EnforceReadiness = {
  windowHours: number;
  shadowSince: string | null;
  mismatches: number;
  errors: number;
  ready: boolean;
  reasons: string[];
};

export type EngineStatus = {
  mode: PolicyMode;
  engineAvailable: boolean;
  schemaVersion: string;
  customVersion: number | null;
  customValid: boolean;
  customFallbacks: number;
  baselineDigest: string;
  workspaces: number;
  counters: Record<string, Record<string, number>>;
  p95Ms: number;
  samples: number;
  /** The draft shadow's own evaluation, on top of the live comparison; 0 samples without a draft. */
  draftP95Ms: number;
  draftSamples: number;
  retentionDays: number;
  pending: number;
  dropped: number;
  enforce: EnforceReadiness;
};

const mode = (value: unknown): PolicyMode => (MODES.includes(value as PolicyMode) ? (value as PolicyMode) : "shadow");

export function readStatus(raw: unknown): EngineStatus | null {
  if (!isRecord(raw)) return null;
  const engine = isRecord(raw.engine) ? raw.engine : {};
  const custom = isRecord(raw.custom) ? raw.custom : {};
  const baseline = isRecord(raw.baseline) ? raw.baseline : {};
  const latency = isRecord(raw.latency) ? raw.latency : {};
  const draftLatency = isRecord(raw.draft_latency) ? raw.draft_latency : {};
  const log = isRecord(raw.decision_log) ? raw.decision_log : {};
  const enforce = isRecord(raw.enforce) ? raw.enforce : {};
  const counters: Record<string, Record<string, number>> = {};
  if (isRecord(raw.counters)) {
    for (const [point, outcomes] of Object.entries(raw.counters)) {
      if (!isRecord(outcomes)) continue;
      counters[point] = Object.fromEntries(Object.entries(outcomes).map(([key, value]) => [key, num(value)]));
    }
  }
  return {
    mode: mode(raw.mode),
    engineAvailable: engine.available === true,
    schemaVersion: str(engine.schema_version),
    customVersion: optNum(custom.version),
    customValid: custom.valid !== false,
    customFallbacks: isRecord(raw.custom_fallbacks) ? Object.values(raw.custom_fallbacks).reduce<number>((sum, value) => sum + num(value), 0) : 0,
    baselineDigest: str(baseline.digest),
    workspaces: num(baseline.workspaces),
    counters,
    p95Ms: num(latency.p95_ms),
    samples: num(latency.samples),
    draftP95Ms: num(draftLatency.p95_ms),
    draftSamples: num(draftLatency.samples),
    retentionDays: num(log.retention_days),
    pending: num(log.pending),
    dropped: num(log.dropped),
    enforce: {
      windowHours: num(enforce.window_hours),
      shadowSince: str(enforce.shadow_since) || null,
      mismatches: num(enforce.mismatches),
      errors: num(enforce.errors),
      ready: enforce.ready === true,
      reasons: strs(enforce.reasons),
    },
  };
}

export const ENFORCE_REASON_TEXT: Record<string, string> = {
  not_in_shadow: "Switch to shadow first: enforcement needs a shadow period.",
  window_not_elapsed: "The shadow period is not over yet.",
  mismatches_in_window: "Cedar disagreed with the existing checks during the shadow period.",
  errors_in_window: "Cedar evaluations failed during the shadow period.",
  custom_set_invalid: "The published custom policies do not load.",
  engine_unavailable: "The Cedar engine is not available on this server.",
  decision_log_pending: "Recent decisions could not be written to the log yet; try again shortly.",
  decision_log_records_dropped: "Decision records were dropped (log buffer full) since shadow was selected; select shadow again to start a complete window.",
};

export function enforceBlockers(status: EngineStatus): string[] {
  return status.enforce.reasons.map((reason) => ENFORCE_REASON_TEXT[reason] ?? `Not ready (${reason}).`);
}

/** The header card's readiness line: "Enforce ready", "Enforce ready in 6 h" (only the window left) or "not ready". */
export function readinessLine(status: EngineStatus, now: Date = new Date()): string {
  if (status.mode === "enforce") return "Enforcing";
  if (status.enforce.ready) return "Enforce ready";
  const since = status.enforce.shadowSince ? serverDate(status.enforce.shadowSince) : null;
  if (status.enforce.reasons.length === 1 && status.enforce.reasons[0] === "window_not_elapsed" && since && !Number.isNaN(since.getTime())) {
    const hours = Math.max(1, Math.ceil((since.getTime() + status.enforce.windowHours * 3600_000 - now.getTime()) / 3600_000));
    return `Enforce ready in ${hours} h`;
  }
  return "Enforce not ready";
}

/** Counters summed over every point: `{match, mismatch, custom_policy, error}`. */
export function outcomeTotals(counters: Record<string, Record<string, number>>): Record<string, number> {
  const totals: Record<string, number> = {};
  for (const outcomes of Object.values(counters)) {
    for (const [outcome, count] of Object.entries(outcomes)) totals[outcome] = (totals[outcome] ?? 0) + count;
  }
  return totals;
}
