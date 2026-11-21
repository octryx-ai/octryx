// Value readers shared by the coding session model: named values, counts, records, latest plan/session/event.
import type { CodingAgentChatSession } from "./codingTypes";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkStateEvent } from "../work/workSyncWorkflowTypes";

export type UnknownRecord = Record<string, unknown>;
export function latestAgentSessions(agentSessions: CodingAgentChatSession[]): CodingAgentChatSession[] {
  return [...agentSessions].sort((left, right) => {
    const leftTime = new Date(left.started_at || "").getTime();
    const rightTime = new Date(right.started_at || "").getTime();
    return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
  });
}

export function latestStateEvent(stateEvents: WorkStateEvent[]): WorkStateEvent | null {
  const committedEvents = stateEvents.filter((event) => !event.dry_run && event.to_state);
  return [...committedEvents].sort((left, right) => {
    const leftTime = new Date(left.created_at || "").getTime();
    const rightTime = new Date(right.created_at || "").getTime();
    return (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
  })[0] || null;
}

export function latestByVersion(plans: WorkChangePlan[]): WorkChangePlan | null {
  return [...plans].sort((left, right) => right.version - left.version)[0] || null;
}

export function extractNamedValues(value: unknown, keys: string[] = ["name", "displayName", "key", "id"]): string[] {
  if (Array.isArray(value)) {
    return value.flatMap((entry) => extractNamedValues(entry, keys));
  }
  if (typeof value === "string") {
    return value.trim() ? [value.trim()] : [];
  }
  if (typeof value === "number") {
    return [String(value)];
  }
  const record = recordValue(value);
  if (!record) {
    return [];
  }
  for (const key of keys) {
    const current = record[key];
    if (typeof current === "string" && current.trim()) {
      return [current.trim()];
    }
  }
  return [];
}

export function countValues(value: unknown): number {
  if (Array.isArray(value)) {
    return value.length;
  }
  if (value && typeof value === "object") {
    return Object.keys(value).length;
  }
  return value == null || value === "" ? 0 : 1;
}

export function hasFailedEvidence(value: unknown): boolean {
  const text = JSON.stringify(value || {}).toLowerCase();
  return /\b(failed|blocked|error|declined|rejected|critical)\b/.test(text);
}

export function recordValue(value: unknown): UnknownRecord | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as UnknownRecord)
    : null;
}


export function listLength(value: unknown): number {
  return Array.isArray(value) ? value.length : 0;
}

export function uniqueStrings(values: string[]): string[] {
  return [...new Set(values.map((value) => value.trim()).filter(Boolean))].sort((a, b) =>
    a.localeCompare(b),
  );
}
