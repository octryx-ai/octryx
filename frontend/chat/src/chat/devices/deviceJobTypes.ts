// Types of a thread's device jobs: the job, its stream events, approvals and live refusals.
import type { Remedy } from "./remedyModel";

export type JobEvent = { seq: number; type: string; body: Record<string, unknown> };

export type JobApproval = {
  id: string;
  tool: string;
  inputPreview: string;
  status: string;
  canAllowJobEdits: boolean;
  expiresAt: string | null;
};

/** A live refusal of the platform (`device_job_event` `tool_denied`, backend), before its `tool_result` arrives. */
export type JobDenial = { turnId: string | null; tool: string; message: string; remedy: Remedy | null };

export type DeviceJob = {
  id: string;
  deviceId: string;
  deviceName: string;
  folder: string;
  profile: string;
  /** The model the device reported for the turn; `null` until it did. */
  model: string | null;
  /** The model the chat asked for; "" means the device's default. */
  requestedModel: string;
  /** The coding engine the job's session runs on (`claude_code` | `codex`); null until the job's first offer (= Claude Code). */
  engine: string | null;
  status: string;
  statusReason: string | null;
  turnId: string | null;
  stopping: boolean;
  lastEventSeq: number;
  events: JobEvent[];
  approvals: JobApproval[];
  denials: JobDenial[];
};
