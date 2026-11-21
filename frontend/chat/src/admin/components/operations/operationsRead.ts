// Reading the Operations › Live payload into typed runs, devices and seats, sorted by urgency.
import { readSeat } from "../../../chat/cost/seatEquivalent";
import type {
  OperationsLive, OpsDevice, OpsItem, OpsJob, OpsProblem, OpsRef, OpsRun, OpsSeat, OpsWhere, RunState,
} from "./operationsTypes";
import { list, num, record, text } from "./operationsValues";

const RUN_STATES: RunState[] = ["looping", "problem", "silent", "needs_you", "stopped", "working"];

function ref(value: unknown): OpsRef | null {
  const item = record(value);
  return item && text(item.id) ? { id: text(item.id), name: text(item.name) || "Someone", isMe: item.is_me === true } : null;
}

function problemOf(value: unknown): OpsProblem | null {
  const item = record(value);
  if (!item || !text(item.key)) return null;
  return {
    key: text(item.key),
    reasonCode: text(item.reason_code) || text(item.key).split(":").pop() || "",
    severity: item.severity === "problem" ? "problem" : "attention",
    title: text(item.title),
  };
}
const problemsOf = (value: unknown): OpsProblem[] =>
  list(value).map(problemOf).filter((problem): problem is OpsProblem => problem !== null);

function whereOf(value: unknown): OpsWhere | null {
  const item = record(value);
  if (!item) return null;
  const kind = item.kind === "device" || item.kind === "terminal" ? item.kind : "server";
  return {
    kind,
    deviceId: text(item.device_id),
    deviceName: text(item.device_name),
    folder: text(item.folder),
    model: text(item.model),
    online: typeof item.online === "boolean" ? item.online : null,
    label: text(item.label),
  };
}

function jobOf(value: unknown): OpsJob | null {
  const item = record(value);
  if (!item || !text(item.id)) return null;
  return {
    id: text(item.id),
    status: text(item.status),
    statusReason: text(item.status_reason),
    folder: text(item.folder),
    deviceId: text(item.device_id),
    lastEventAt: text(item.last_event_at) || null,
    costUsd: num(item.cost_usd),
  };
}

function itemOf(value: unknown): OpsItem | null {
  const item = record(value);
  if (!item || !text(item.id)) return null;
  return {
    id: text(item.id),
    title: text(item.title) || text(item.id),
    status: text(item.status),
    iteration: num(item.iteration) ?? 1,
    model: text(item.model),
    branch: text(item.branch),
    startedAt: text(item.started_at) || null,
    finishedAt: text(item.finished_at) || null,
    dispatches5m: num(item.dispatches_5m) ?? 0,
    sessionId: text(item.session_id),
    job: jobOf(item.job),
    problems: problemsOf(item.problems),
  };
}

function stateOf(value: unknown): RunState {
  return (RUN_STATES as string[]).includes(String(value)) ? (value as RunState) : "working";
}

function runOf(value: unknown): OpsRun | null {
  const item = record(value);
  if (!item || !text(item.id)) return null;
  const node = record(item.current_node);
  const workItem = record(item.work_item);
  return {
    id: text(item.id),
    // The workflow's own title, without the work item key (the key has its own place in the meta line).
    title: text(item.workflow_title) || text(item.title) || "Run",
    workspace: ref(item.workspace),
    workItem: workItem && text(workItem.key)
      ? { id: text(workItem.id), key: text(workItem.key), title: text(workItem.title) } : null,
    state: stateOf(item.state),
    status: text(item.status),
    waitingKind: text(item.waiting_kind),
    pauseReason: text(item.pause_reason),
    currentNode: node ? text(node.title) || text(node.id) : "",
    lastEventAt: text(item.last_event_at) || null,
    idleSeconds: num(item.idle_seconds),
    requestedBy: ref(item.requested_by),
    responsible: ref(item.responsible),
    where: whereOf(item.where),
    costUsd: num(item.cost_usd),
    seat: readSeat(item, "seat_api_equivalent_usd", "seat_unpriced_calls"),
    sessionId: text(item.session_id),
    problems: problemsOf(item.problems),
    items: list(item.items).map(itemOf).filter((entry): entry is OpsItem => entry !== null),
  };
}

function deviceOf(value: unknown): OpsDevice | null {
  const item = record(value);
  if (!item || !text(item.id)) return null;
  return {
    id: text(item.id),
    name: text(item.name) || "Device",
    owner: ref(item.owner),
    online: item.online === true,
    lastSeenAt: text(item.last_seen_at) || null,
    clientVersion: text(item.client_version),
    servedVersion: text(item.served_version),
    outdated: item.outdated === true,
    paused: item.paused === true,
    jobsRunning: num(item.jobs_running) ?? 0,
    maxParallelJobs: num(item.max_parallel_jobs) ?? 0,
  };
}

function seatOf(value: unknown): OpsSeat | null {
  const item = record(value);
  const user = ref(item?.user);
  if (!item || !user) return null;
  return {
    user,
    fiveHourPct: num(item.five_hour_pct),
    fiveHourResetsAt: text(item.five_hour_resets_at) || null,
    sevenDayPct: num(item.seven_day_pct),
  };
}

/** The live view's payload; runs in the order of their state's urgency (stable, so the server's order holds within). */
export function readOperations(payload: unknown): OperationsLive {
  const body = record(payload);
  const counts = record(body?.counts);
  const runs = list(body?.runs).map(runOf).filter((run): run is OpsRun => run !== null);
  return {
    generatedAt: text(body?.generated_at) || null,
    viewerId: text(record(body?.viewer)?.id),
    counts: {
      working: num(counts?.working) ?? 0,
      needs_you: num(counts?.needs_you) ?? 0,
      silent: num(counts?.silent) ?? 0,
      looping: num(counts?.looping) ?? 0,
      problem: num(counts?.problem) ?? 0,
      stopped: num(counts?.stopped) ?? 0,
      // changed: the last 24 hours (was cost_today_usd).
      cost24hUsd: num(counts?.cost_24h_usd),
      seatApiEquivalent24hUsd: num(counts?.seat_api_equivalent_24h_usd),
    },
    runs: sortByUrgency(runs),
    devices: list(body?.devices).map(deviceOf).filter((device): device is OpsDevice => device !== null),
    seats: list(body?.seats).map(seatOf).filter((seat): seat is OpsSeat => seat !== null),
  };
}

export function sortByUrgency(runs: OpsRun[]): OpsRun[] {
  return runs
    .map((run, index) => ({ run, index }))
    .sort((a, b) => RUN_STATES.indexOf(a.run.state) - RUN_STATES.indexOf(b.run.state) || a.index - b.index)
    .map(({ run }) => run);
}
