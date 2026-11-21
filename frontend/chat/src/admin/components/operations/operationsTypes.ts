// Operations › Live payload types: runs, items, jobs, devices, seats and counts.
import type { SeatFigures } from "../../../chat/cost/seatEquivalent";

// changed: "stopped" = paused by an emergency stop; ranked between needs_you and working.
export type RunState = "working" | "needs_you" | "silent" | "looping" | "problem" | "stopped";
export type OpsRef = { id: string; name: string; isMe: boolean };
export type OpsProblem = { key: string; reasonCode: string; severity: "problem" | "attention"; title: string };

export type OpsWhere = {
  kind: "device" | "server" | "terminal";
  deviceId: string;
  deviceName: string;
  folder: string;
  model: string;
  online: boolean | null;
  label: string;
};

export type OpsJob = {
  id: string;
  status: string;
  statusReason: string;
  folder: string;
  deviceId: string;
  lastEventAt: string | null;
  costUsd: number | null;
};

export type OpsItem = {
  id: string;
  title: string;
  status: string;
  iteration: number;
  model: string;
  branch: string;
  startedAt: string | null;
  finishedAt: string | null;
  dispatches5m: number;
  sessionId: string;
  job: OpsJob | null;
  problems: OpsProblem[];
};

export type OpsRun = {
  id: string;
  title: string;
  workspace: OpsRef | null;
  workItem: { id: string; key: string; title: string } | null;
  state: RunState;
  status: string;
  waitingKind: string;
  // Why a paused run stopped ("emergency_stop", a limit); "" otherwise.
  pauseReason: string;
  currentNode: string;
  lastEventAt: string | null;
  idleSeconds: number | null;
  requestedBy: OpsRef | null;
  responsible: OpsRef | null;
  where: OpsWhere | null;
  // The API cost; `seat` beside it is what the run's seat calls would cost via the API at list price (Alex
  // ), never added to it.
  costUsd: number | null;
  seat: SeatFigures;
  sessionId: string;
  problems: OpsProblem[];
  items: OpsItem[];
};

export type OpsDevice = {
  id: string;
  name: string;
  owner: OpsRef | null;
  online: boolean;
  lastSeenAt: string | null;
  clientVersion: string;
  servedVersion: string;
  outdated: boolean;
  paused: boolean;
  jobsRunning: number;
  maxParallelJobs: number;
};

export type OpsSeat = { user: OpsRef; fiveHourPct: number | null; fiveHourResetsAt: string | null; sevenDayPct: number | null };

// cost24hUsd is API cost only; seatApiEquivalent24hUsd is what the seat calls would cost via the API, never added to it.
export type OpsCounts = Record<RunState, number> & { cost24hUsd: number | null; seatApiEquivalent24hUsd: number | null };

export type OperationsLive = {
  generatedAt: string | null;
  // The caller's user id (contract changed).
  viewerId: string;
  counts: OpsCounts;
  runs: OpsRun[];
  devices: OpsDevice[];
  seats: OpsSeat[];
};
