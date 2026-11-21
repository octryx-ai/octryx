// The model calls behind one answer, seat and device turns included. The server
// lists every call of the turn with model, tokens and time; a call's stored content (redacted, bounded) loads only
// when the person opens it. Pure: no React.
import type { TurnTrace, TurnTraceCall } from "../chatThreadTypes";

// Said when the platform cannot link gateway calls to a device turn. It does not claim where the calls went: a
// resumed turn sends its calls under a new launcher key that is not matched yet.
export const DEVICE_NO_CALLS_NOTE =
  "No gateway calls are linked to this turn. Claude Code ran on the device; "
  + "this trace shows the outcome, model and usage the device reported.";
export const DEVICE_CALLS_NOTE =
  "Claude Code ran on the device. These are the model calls it sent through the platform.";

export type CallTokens = TurnTraceCall["tokens"];

export function traceCalls(trace: TurnTrace): TurnTraceCall[] {
  return Array.isArray(trace.calls) ? trace.calls : [];
}

export function callTotals(calls: TurnTraceCall[]): CallTokens {
  return calls.reduce<CallTokens>((sum, call) => ({
    input: sum.input + (call.tokens?.input ?? 0),
    output: sum.output + (call.tokens?.output ?? 0),
    cacheRead: sum.cacheRead + (call.tokens?.cacheRead ?? 0),
    cacheCreation: sum.cacheCreation + (call.tokens?.cacheCreation ?? 0),
  }), { input: 0, output: 0, cacheRead: 0, cacheCreation: 0 });
}

const count = (value: number) => new Intl.NumberFormat("de-CH").format(value);

// "14:02:31": the call's local time; empty without a time.
export function callTime(iso: string | null): string {
  if (!iso) return "";
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("de-CH", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

// "1'200 in · 7 out · 3 cached · 1.5 s · tool_use": what one call cost and how it ended.
export function callFacts(call: TurnTraceCall): string {
  const tokens = call.tokens ?? { input: 0, output: 0, cacheRead: 0, cacheCreation: 0 };
  const parts = [`${count(tokens.input)} in`, `${count(tokens.output)} out`];
  if (tokens.cacheRead) parts.push(`${count(tokens.cacheRead)} cached`);
  if (tokens.cacheCreation) parts.push(`${count(tokens.cacheCreation)} cache write`);
  if (typeof call.durationMs === "number") parts.push(`${(call.durationMs / 1000).toFixed(1)} s`);
  if (call.stopReason) parts.push(call.stopReason);
  return parts.join(" · ");
}

// The section's heading line: how many calls and what they used together.
export function callsHeading(calls: TurnTraceCall[]): string {
  const totals = callTotals(calls);
  const noun = calls.length === 1 ? "model call" : "model calls";
  const cached = totals.cacheRead ? ` · ${count(totals.cacheRead)} cached` : "";
  return `${calls.length} ${noun} · ${count(totals.input)} in · ${count(totals.output)} out${cached}`;
}

// What the device note says: no gateway calls are linked, or the listed calls passed through the platform.
export function deviceNote(trace: TurnTrace): string | null {
  if (trace.promptOnDevice) return DEVICE_NO_CALLS_NOTE;
  if (trace.provider === "device" && traceCalls(trace).length > 0) return DEVICE_CALLS_NOTE;
  return null;
}
