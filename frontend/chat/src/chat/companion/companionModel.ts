// Octryx companion, stage 1: one place for what needs the person, what runs and what is done.
// Pure functions only: reading the attention payload (GET /api/v1/attention), the octopus' face and eight arms, the
// notification rules and the request an action sends. Every field is read tolerantly; unknown values are dropped,
// never shown.
import { groupAttention, needsYou } from "./companionGroups";
import {
  ARM_COUNT, DEFAULT_QUIET_HOURS,
  type ArmNode, type Attention, type AttentionAction, type AttentionItem, type AttentionRequest, type FaceState,
  type NodeState, type QuietHours, type RunState, type RunningAgent,
} from "./companionTypes";
import { record, str } from "./companionValues";

const CLOCK = /^([01]\d|2[0-3]):[0-5]\d$/;

/** Overall face: worry on a problem, open when something needs the person, sleep in quiet hours or with nothing on. */
export function faceState(attention: Attention | null): FaceState {
  if (!attention) return "sleep";
  if (attention.items.some((item) => item.kind === "problem") || attention.running.some((run) => run.state === "problem")) return "worry";
  if (needsYou(attention.items).length || attention.running.some((run) => run.state === "needs_you")) return "open";
  if (attention.quiet.active) return "sleep";
  return attention.running.length || attention.items.length ? "calm" : "sleep";
}

const NODE_OF: Record<RunState, NodeState> = { working: "run", needs_you: "wait", done: "done", problem: "fail" };

/** Eight arm nodes: one per run; more than eight runs put "+N" on the eighth. Unreachable: all off. */
export function armNodes(running: RunningAgent[], reachable = true): ArmNode[] {
  if (!reachable) return Array.from({ length: ARM_COUNT }, () => ({ state: "off", label: "Not connected", more: 0 }));
  const nodes: ArmNode[] = running.slice(0, ARM_COUNT).map((run) => ({ state: NODE_OF[run.state], label: run.label, more: 0 }));
  if (running.length > ARM_COUNT) nodes[ARM_COUNT - 1] = { state: "run", label: `${running.length - (ARM_COUNT - 1)} more runs`, more: running.length - (ARM_COUNT - 1) };
  while (nodes.length < ARM_COUNT) nodes.push({ state: "idle", label: "Free", more: 0 });
  return nodes;
}

/** Whether an arm moves: only while something works (never under reduced motion, which the view decides). */
export const armsMoving = (nodes: ArmNode[]) => nodes.some((node) => node.state === "run");

/**
 * Notify rules: questions, gates, approvals, handoffs, done and problems notify; budget from 80 %, allowance from 95 %.
 * Phase changes, finished turns and green tests never become attention items, so they stay silent.
 */
export function notifies(item: AttentionItem): boolean {
  if (item.kind === "budget") return item.percent === null || item.percent >= 80;
  if (item.kind === "allowance") return item.percent === null || item.percent >= 95;
  return true;
}

/** Items new since the previous load that notify. The first load is the baseline and announces nothing. */
export function itemsToNotify(previous: Set<string> | null, attention: Attention): AttentionItem[] {
  if (previous === null || attention.quiet.active) return [];
  return attention.items.filter((item) => !previous.has(item.key) && notifies(item));
}

/** "Octryx: 1 needs you, 3 working" — the button's accessible name. */
export function companionLabel(attention: Attention | null): string {
  if (!attention) return "Octryx: not connected";
  // The same groups as the panel, so the name never counts a run twice.
  const groups = groupAttention(attention.items, attention.running);
  const working = groups.running.filter((run) => run.state === "working").length;
  const parts = [
    groups.needs.length ? `${groups.needs.length} needs you` : "",
    working ? `${working} working` : "",
    groups.done.length ? `${groups.done.length} done` : "",
    groups.problems.length ? `${groups.problems.length} ${groups.problems.length === 1 ? "problem" : "problems"}` : "",
  ].filter(Boolean);
  return `Octryx: ${parts.length ? parts.join(", ") : "nothing needs you"}`;
}

/** The request an action sends: free text goes into body[input.field]. */
export function buildActionRequest(action: AttentionAction, text = ""): AttentionRequest | { error: string } {
  const body = { ...action.request.body };
  if (action.input) {
    const value = text.trim();
    if (action.input.required && !value) return { error: `${action.input.label || "An answer"} is required.` };
    if (value) body[action.input.field] = value;
  }
  return { ...action.request, body };
}

/** Seconds left until an item expires (device approvals); null without an expiry. */
export function secondsLeft(expiresAt: string | null, now = Date.now()): number | null {
  if (!expiresAt) return null;
  const at = Date.parse(expiresAt);
  return Number.isFinite(at) ? Math.max(0, Math.floor((at - now) / 1000)) : null;
}

export function countdownText(seconds: number | null): string {
  if (seconds === null) return "";
  if (seconds === 0) return "Expired";
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")} left`;
}

/** quiet_hours of the notification preferences; the default when missing or malformed. */
export function readQuietHours(payload: unknown): { quiet: QuietHours; stored: boolean } {
  const quiet = record(record(payload)?.quiet_hours);
  if (!quiet || !CLOCK.test(str(quiet.start)) || !CLOCK.test(str(quiet.end))) return { quiet: { ...DEFAULT_QUIET_HOURS }, stored: false };
  return { quiet: { enabled: quiet.enabled !== false, start: str(quiet.start), end: str(quiet.end), timezone: str(quiet.timezone) || DEFAULT_QUIET_HOURS.timezone }, stored: true };
}

export const validQuietHours = (quiet: QuietHours) => CLOCK.test(quiet.start) && CLOCK.test(quiet.end) && quiet.start !== quiet.end;

/** The PUT body: quiet hours plus the stored channel switches unchanged (the server takes a partial update). */
export function quietHoursBody(preferences: unknown, quiet: QuietHours): Record<string, unknown> {
  const current = record(preferences) ?? {};
  const keep = Object.fromEntries(Object.entries(current).filter(([key, value]) => key.endsWith("_enabled") && typeof value === "boolean"));
  return { ...keep, quiet_hours: { ...quiet } };
}
