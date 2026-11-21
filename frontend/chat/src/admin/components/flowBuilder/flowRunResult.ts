// Readable view of one flow run, built from the backend trace contract (read-only):
// - `run.merged_output_json` = { final, nodes } (services/flow_orchestration/dag/execute.py):
//   `final` is the output step's output `{ result: <input snapshot> }`, or the last step's
//   output when there is no output step; `nodes` repeats every step's output.
// - `run.acceptance` (services/runtime_acceptance.py), `run.failure`
//   (services/runtime_failure_taxonomy.py), `run.runtime_lease` (flow_orchestration/recovery.py).
// - a paused approval step's output = { reason, approval_id, approval: { title, prompt, required_role, … } }.
// - an agent step's output carries `turn: { state, … }` (flow_agent_step.py): the
//   child turn's closed `turn_execution_summary.v1` state. `finished_unverified` means the agent's turn
//   finished, not that its result was checked; the run outcome says so instead of claiming success.
// Timestamps are naive UTC ISO strings. Nothing here is invented: the outcome is the run
// status, notices come from failure/acceptance/pause facts, and every raw fact stays available
// in Diagnostics or the raw result.
import type { FlowRunTracePayload } from "./flowRunTypes";
import { failureCode, failureMessage } from "./flowFailureMessages";
import { asRecord } from "./flowTraceFormat";
import { flowRunStepCounts } from "./flowRunStepCounts";
import { formatDateTime } from "../../utils/dateTime";

export type RunTone = "ok" | "error" | "attention" | "warning" | "neutral";
export type RunNotice = { tone: RunTone; title: string; detail?: string };
export type ResultField = { label: string; value: string; multiline: boolean };
export type RunResultBody =
  | { kind: "fields"; heading: string; fields: ResultField[] }
  | { kind: "list"; heading: string; items: string[] }
  | { kind: "text"; heading: string; text: string }
  | { kind: "message"; text: string }
  | { kind: "none" };
export type DiagnosticRow = { label: string; value: string };

export type FlowRunResultView = {
  outcome: string;
  tone: RunTone;
  duration: string | null;
  notices: RunNotice[];
  result: RunResultBody;
  raw: Record<string, unknown> | null;
  diagnostics: DiagnosticRow[];
  rawFacts: Record<string, unknown>;
};

const OUTCOME: Record<string, [string, RunTone]> = {
  completed: ["Completed", "ok"],
  failed: ["Failed", "error"],
  paused: ["Waiting for review", "attention"],
  cancelled: ["Cancelled", "warning"],
  running: ["Running", "neutral"],
  pending: ["Queued", "neutral"],
};

export function humanize(value: unknown): string {
  const text = String(value ?? "").replace(/[_-]+/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "";
}

function parseUtc(value: unknown): Date | null {
  if (typeof value !== "string" || !value.trim()) return null;
  const hasZone = /([zZ]|[+-]\d{2}:?\d{2})$/.test(value.trim());
  const date = new Date(hasZone ? value : `${value}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function readableTime(value: unknown): string {
  const date = parseUtc(value);
  return formatDateTime(date);
}

export function readableDuration(start: unknown, end: unknown): string | null {
  const from = parseUtc(start);
  const to = parseUtc(end);
  if (!from || !to || to < from) return null;
  const ms = to.getTime() - from.getTime();
  if (ms < 1000) return "under 1 s";
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)} s`;
  const minutes = Math.floor(ms / 60_000);
  return `${minutes} min ${Math.round((ms % 60_000) / 1000)} s`;
}

function displayValue(value: unknown): { value: string; multiline: boolean } {
  if (value === null || value === undefined) return { value: "—", multiline: false };
  if (typeof value === "string") return { value, multiline: value.includes("\n") };
  if (typeof value === "number" || typeof value === "boolean") return { value: String(value), multiline: false };
  if (Array.isArray(value) && value.every((item) => item === null || typeof item !== "object")) {
    return { value: value.map((item) => String(item)).join(", "), multiline: false };
  }
  return { value: JSON.stringify(value, null, 2), multiline: true };
}

// The terminal result: `final.result` when the final output is the output step's envelope,
// otherwise `final` itself. `nodes` is not shown here (it repeats every step; see raw result).
export function terminalResult(mergedOutput: unknown, status: string): RunResultBody {
  const merged = asRecord(mergedOutput);
  if (!("final" in merged)) {
    return status === "completed" ? { kind: "message", text: "The run completed without output." } : { kind: "none" };
  }
  const final = merged.final;
  const finalRecord = asRecord(final);
  const keys = Object.keys(finalRecord);
  const value = keys.length === 1 && keys[0] === "result" ? finalRecord.result : final;
  const heading = status === "completed" ? "Final output" : "Partial output (the run did not complete)";
  if (value === null || value === undefined || (typeof value === "object" && !Array.isArray(value) && !Object.keys(value).length)) {
    return { kind: "message", text: status === "completed" ? "The run completed without output." : "No output was produced." };
  }
  if (Array.isArray(value)) {
    return value.every((item) => item === null || typeof item !== "object")
      ? { kind: "list", heading, items: value.map((item) => String(item)) }
      : { kind: "text", heading, text: JSON.stringify(value, null, 2) };
  }
  if (typeof value !== "object") return { kind: "text", heading, text: String(value) };
  const fields = Object.entries(value as Record<string, unknown>).map(([key, item]) => ({ label: humanize(key), ...displayValue(item) }));
  return { kind: "fields", heading, fields };
}

// Agent steps whose turn finished but whose result was not verified (the turn's closed state),
// named by the agent's own recorded name when there is one; node ids stay in Step details.
export function unverifiedAgentSteps(trace: FlowRunTracePayload): { nodeId: string; agentName: string | null }[] {
  return trace.node_runs
    .filter((nodeRun) => nodeRun.status === "completed")
    .filter((nodeRun) => {
      const turn = asRecord(asRecord(nodeRun.output).turn);
      return turn.state === "finished_unverified";
    })
    .map((nodeRun) => {
      const name = asRecord(asRecord(nodeRun.output).agent).name;
      return { nodeId: nodeRun.node_id, agentName: typeof name === "string" && name.trim() ? name.trim() : null };
    });
}

function runNotices(trace: FlowRunTracePayload): RunNotice[] {
  const { run } = trace;
  const notices: RunNotice[] = [];
  const unverified = unverifiedAgentSteps(trace);
  if (unverified.length) {
    const names = unverified.map((step) => step.agentName).filter((name): name is string => Boolean(name));
    const who = names.length ? `${[...new Set(names)].join(", ")}: the agent's` : "The agent's";
    notices.push({
      tone: "attention",
      title: "Agent result not verified",
      detail: `${who} turn finished, but no check confirmed that its answer meets the step's goal. Review the result before relying on it.`,
    });
  }
  const failure = asRecord(run.failure);
  const acceptance = asRecord(run.acceptance);
  const failedStep = trace.node_runs.find((nodeRun) => nodeRun.status === "failed");
  const known = failureMessage(trace);
  if (known) {
    // Typed failure code → plain message; the code, error type and step id stay in Diagnostics.
    notices.push({ tone: "error", title: known.title, detail: known.action });
  } else if (Object.keys(failure).length || run.status === "failed") {
    const summary = String(failure.summary || run.last_error || "The run failed.").replace(/\s+error_type=\S+$/, "");
    const parts = [
      failedStep ? `Step ${failedStep.node_id}${failedStep.error ? `: ${failedStep.error}` : ""}` : "",
      failure.required_action ? `Next: ${humanize(failure.required_action)}` : "",
      failure.retryable === true ? "Retrying may help." : failure.retryable === false ? "Retrying will not help without a change." : "",
    ].filter(Boolean);
    notices.push({ tone: "error", title: summary, detail: parts.join(" · ") || undefined });
  }
  const pausedStep = trace.node_runs.find((nodeRun) => nodeRun.status === "paused");
  if (run.status === "paused" || pausedStep) {
    const output = asRecord(pausedStep?.output);
    const approval = asRecord(output.approval);
    const where = pausedStep ? ` at step ${pausedStep.node_id}` : "";
    if (Object.keys(approval).length || output.approval_id) {
      const role = approval.required_role ? `Requires role: ${String(approval.required_role)}.` : "";
      notices.push({
        tone: "attention",
        title: `Approval required${where}${approval.title ? `: ${String(approval.title)}` : ""}`,
        detail: [approval.prompt ? String(approval.prompt) : "", role].filter(Boolean).join(" ") || undefined,
      });
    } else {
      notices.push({ tone: "attention", title: `Review required${where}`, detail: String(output.reason || acceptance.reason || "") || undefined });
    }
  } else if (acceptance.review_required === true && run.status !== "failed") {
    notices.push({ tone: "attention", title: "Review needed", detail: String(acceptance.reason || "") || undefined });
  }
  const warnings = Number(acceptance.warning_count || 0);
  if (run.status === "completed" && (acceptance.state === "warnings" || warnings > 0)) {
    notices.push({
      tone: "warning",
      title: `Completed with ${warnings || "some"} validation warning${warnings === 1 ? "" : "s"}`,
      detail: String(acceptance.reason || "") || undefined,
    });
  }
  if (asRecord(run.runtime_lease).is_stale === true) {
    notices.push({ tone: "warning", title: "The run stopped reporting progress", detail: "Its lease expired. Use Recover run to continue it." });
  }
  return notices;
}

function joinFacts(...parts: unknown[]): string {
  const text = parts.filter((part) => part !== undefined && part !== null && part !== "").map(String).join(" · ");
  return text || "—";
}

function runDiagnostics(trace: FlowRunTracePayload): DiagnosticRow[] {
  const { run } = trace;
  const lease = asRecord(run.runtime_lease);
  const acceptance = asRecord(run.acceptance);
  const failure = asRecord(run.failure);
  const progress = asRecord(run.progress);
  const stepCounts = flowRunStepCounts(trace.node_runs);
  const rows: DiagnosticRow[] = [
    { label: "Run", value: run.id },
    { label: "Revision", value: run.flow_definition_version_id || "—" },
    { label: "Status", value: run.status },
    { label: "Pattern", value: humanize(run.pattern_type) || "—" },
    { label: "Started", value: readableTime(run.created_at) },
    { label: "Finished", value: readableTime(run.completed_at) },
    // One count per step by its latest attempt; skipped branches and retries are named.
    { label: "Steps", value: joinFacts(stepCounts.summary, stepCounts.attemptsNote, run.total_steps != null ? `${run.total_steps} planned` : "") },
  ];
  if (run.session_id) rows.push({ label: "Session", value: run.session_id });
  if (Object.keys(progress).length) rows.push({ label: "Progress", value: joinFacts(humanize(progress.phase), progress.current_node_id, readableTime(progress.checkpointed_at)) });
  if (Object.keys(lease).length) {
    rows.push({
      label: "Lease",
      value: joinFacts(humanize(lease.status) || "Unknown", lease.is_stale === true ? "stale" : "not stale", lease.owner,
        lease.last_heartbeat_at ? `heartbeat ${readableTime(lease.last_heartbeat_at)}` : "",
        lease.lease_expires_at ? `expires ${readableTime(lease.lease_expires_at)}` : ""),
    });
  }
  if (Object.keys(acceptance).length) {
    rows.push(
      { label: "Flow execution acceptance", value: joinFacts(humanize(acceptance.state), acceptance.accepted === true ? "accepted" : "not accepted", acceptance.review_required === true ? "review required" : "no review required") },
      { label: "Required action", value: humanize(acceptance.required_action) || "—" },
      { label: "Validation", value: joinFacts(humanize(acceptance.validation_status) || "Not run", `${Number(acceptance.warning_count || 0)} warnings`) },
      { label: "Acceptance note", value: joinFacts(acceptance.reason, acceptance.updated_at ? `updated ${readableTime(acceptance.updated_at)}` : "") },
    );
  }
  if (Object.keys(failure).length) {
    rows.push({ label: "Failure code", value: joinFacts(failureCode(trace), asRecord(failure.detail).node_id ? `step ${String(asRecord(failure.detail).node_id)}` : "", asRecord(failure.detail).error_type) || "—" });
    rows.push({
      label: "Failure",
      value: joinFacts(humanize(failure.category), failure.severity, failure.retryable === true ? "retryable" : "not retryable",
        failure.source, failure.error_class_source, failure.summary, failure.created_at ? readableTime(failure.created_at) : ""),
    });
  }
  if (run.last_error) rows.push({ label: "Last error", value: run.last_error });
  return rows;
}

export function flowRunResultView(trace: FlowRunTracePayload): FlowRunResultView {
  const { run } = trace;
  const [baseOutcome, baseTone] = OUTCOME[run.status] ?? [humanize(run.status) || "Unknown", "neutral" as RunTone];
  // A completed run whose agent results are unverified finished executing; it is not a verified success.
  const unverified = run.status === "completed" && unverifiedAgentSteps(trace).length > 0;
  const [outcome, tone]: [string, RunTone] = unverified ? ["Execution finished · result not verified", "attention"] : [baseOutcome, baseTone];
  const merged = asRecord(run.merged_output_json);
  return {
    outcome,
    tone,
    duration: readableDuration(run.created_at, run.completed_at),
    notices: runNotices(trace),
    result: terminalResult(run.merged_output_json, run.status),
    raw: Object.keys(merged).length ? merged : null,
    diagnostics: runDiagnostics(trace),
    rawFacts: {
      runtime_lease: run.runtime_lease ?? null,
      acceptance: run.acceptance ?? null,
      failure: run.failure ?? null,
      progress: run.progress ?? null,
      plan: run.plan ?? null,
    },
  };
}

export function flowRunHeading(trace: FlowRunTracePayload | null, revision: number | undefined): string {
  if (!trace) return `Revision ${revision ?? "—"} · test run`;
  const view = flowRunResultView(trace);
  if (!view.duration) return view.outcome;
  const [first, ...rest] = view.outcome.split(" · ");
  return [`${first} in ${view.duration}`, ...rest].join(" · ");
}
