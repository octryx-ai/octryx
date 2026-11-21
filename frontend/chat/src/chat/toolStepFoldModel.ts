import type { ToolEvent } from "../chatThreadTypes";
import { formatDurationMs, humanizeToolName, visibleToolEvents } from "./traceToolEventValues";
import { summarizeToolEvent } from "./traceUiHelpers";
import { readRoleRefusal, roleRefusalText } from "./roles/myRoleModel";
import { isWritePlanRefusal } from "./approval/writePlanView";
import { remedyOfResult, type Remedy } from "./devices/remedyModel";

// The tool steps of a turn folded into one line: "Used 4 tools · 12 s", expandable to the
// existing per-tool list. A failed step stays visible as its own line, so a failure is never hidden in the fold.
// `remedy`: the refusal's one-click fix (a Workspace tool default), offered as "Allow in this Workspace".
export type ToolStepFailure = { id: string; text: string; blocked?: boolean; raw?: string; remedy?: Remedy };

const POLICY_DENIAL = /(?:Octryx|Octryx) policy denied this tool call(?:\s*\[rule [^\]]*\])?(?:\s*\([^)]*\))?:?\s*([\s\S]*)$/;

/**
 * A step the workspace rules refused ("PreToolUse:Bash hook error: Octryx policy denied this tool
 * call [rule outside-phase-tools] (outside_phase_tools): Phase 'Implement' …" stood red in the chat). It is not a
 * failure of the tool: one quiet line with the rule's reason, the raw text expandable.
 */
export function policyRefusal(id: string, name: string, output: string): ToolStepFailure | null {
  const match = POLICY_DENIAL.exec(output || "");
  if (!match) return null;
  const reason = shorten(match[1] || "");
  return {
    id, blocked: true, raw: output.trim(),
    text: reason ? `${name} blocked by the workspace rules: ${reason}` : `${name} blocked by the workspace rules`,
  };
}
export type ToolStepFold = { label: string; count: number; running: boolean; failures: ToolStepFailure[] };

const MCP_PREFIX = /^mcp__.+?__/;
const TOOL_UNAVAILABLE = /No such tool available/i;

/** A tool id in words, without the MCP server prefix: "mcp__octryx-knowledge__list_workspace_directory" →
 * "list workspace directory". */
export function toolStepWords(raw: string): string {
  return String(raw || "").trim().replace(MCP_PREFIX, "").replace(/[_-]+/g, " ").replace(/\s+/g, " ").trim();
}

/**
 * A tool the agent called that the runtime does not offer ("mcp__…__list_workspace_directory failed:
 * <tool_use_error>Error: No such tool available: …</tool_use_error>" stood red under "Used 12 tools"). The agent
 * carries on without it, so it is one calm line; the raw text opens below it.
 */
export function unavailableTool(id: string, rawName: string, output: string): ToolStepFailure | null {
  if (!TOOL_UNAVAILABLE.test(output || "")) return null;
  const words = toolStepWords(rawName);
  return { id, blocked: true, raw: output.trim(), text: words ? `A tool was not available: ${words}` : "A tool was not available" };
}

/**
 * A tool the person's roles do not grant (roles contract §4: `role_tool_not_granted`, `role_connection_not_granted`,
 * `po_function_required`). Not a failure: one calm line with the API's sentence, the setting and who can change it.
 */
export function roleRefused(id: string, result: unknown): ToolStepFailure | null {
  const refusal = readRoleRefusal(result);
  if (!refusal) return null;
  return { id, blocked: true, text: roleRefusalText(refusal) };
}

const statusOf = (event: ToolEvent) => String(event.status || "").trim().toLowerCase();
const FAILED = new Set(["error", "failed"]);
// The gateway's denied ToolCall row (agent_gateway/contract.py TOOL_CALL_STATUS_DENIED).
const DENIED_BY_POLICY = "denied_by_policy";

/** A refusal that names its one-click fix: the rule's line (or a plain one) with the remedy attached. */
function remedyRefusal(id: string, name: string, summary: string, remedy: Remedy): ToolStepFailure {
  const line = policyRefusal(id, name, summary);
  return { ...(line ?? { id, blocked: true, text: `${name} blocked by the workspace rules` }), remedy };
}
const ACTIVE = new Set(["running", "pending"]);

export function shorten(text: string, max = 140): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max - 1).trimEnd()}…` : flat;
}

/** The one-line summary of a turn's tool steps; null when the turn used no visible tool. */
export function foldToolSteps(events: ToolEvent[]): ToolStepFold | null {
  const visible = visibleToolEvents(events);
  if (!visible.length) return null;
  const running = visible.some((event) => ACTIVE.has(statusOf(event)));
  const total = visible.reduce((sum, event) => sum + Number(event.durationMs || 0), 0);
  const duration = formatDurationMs(total);
  const count = visible.length;
  const noun = count === 1 ? "tool" : "tools";
  const head = running ? `Using tools · ${count} so far` : `Used ${count} ${noun}`;
  const rawNames = new Map(events.map((event) => [event.id, event.toolName]));
  const failed = visible.filter((event) => FAILED.has(statusOf(event)) || statusOf(event) === DENIED_BY_POLICY
    || readRoleRefusal(event.result));
  // A write the gate sent back for the write plan is the model's own next step, not a
  // failure: one quiet line for the turn, however many writes it sent back.
  const planStep = failed.find((event) => isWritePlanRefusal(event.result));
  const failures = failed
    .filter((event) => event === planStep || !isWritePlanRefusal(event.result))
    .map((event) => {
      if (isWritePlanRefusal(event.result)) return writePlanStep(event.id, event.result);
      const byRole = roleRefused(event.id, event.result);
      if (byRole) return byRole;
      const summary = summarizeToolEvent(event);
      const remedy = remedyOfResult(event.result);
      if (remedy) return remedyRefusal(event.id, humanizeToolName(event.toolName) || "A tool", summary, remedy);
      if (statusOf(event) === DENIED_BY_POLICY) {
        return { id: event.id, blocked: true, text: `${humanizeToolName(event.toolName) || "A tool"} blocked by the workspace rules` };
      }
      const unavailable = unavailableTool(event.id, rawNames.get(event.id) || event.toolName, summary);
      if (unavailable) return unavailable;
      const name = humanizeToolName(event.toolName) || "A tool";
      const refusal = policyRefusal(event.id, name, summary);
      if (refusal) return refusal;
      return { id: event.id, text: summary ? `${name} failed: ${shorten(summary)}` : `${name} failed` };
    });
  return { label: duration && !running ? `${head} · ${duration}` : head, count, running, failures };
}

/** The quiet line for a write the gate sent back to be put into the write plan first. */
export function writePlanStep(id: string, result: unknown): ToolStepFailure {
  let raw = "";
  try {
    raw = typeof result === "string" ? result : JSON.stringify(result, null, 2);
  } catch {
    raw = "";
  }
  return { id, blocked: true, raw, text: "Preparing the write plan" };
}

/** A device job's tool steps folded the same way (no durations: device events carry no timing). */
export type DeviceToolStep = {
  key: string;
  tool: string;
  status: "running" | "done" | "error";
  output: string;
  /** The refusal's one-click fix, when the device event carries one (`tool_result.remedy`). */
  remedy?: Remedy | null;
};

export function foldDeviceToolSteps(steps: DeviceToolStep[]): ToolStepFold | null {
  if (!steps.length) return null;
  const running = steps.some((step) => step.status === "running");
  const count = steps.length;
  const label = running ? `Using tools · ${count} so far` : `Used ${count} ${count === 1 ? "tool" : "tools"}`;
  const failures = steps
    .filter((step) => step.status === "error")
    .map((step) => {
      const byRole = roleRefused(step.key, step.output);
      if (byRole) return byRole;
      const unavailable = unavailableTool(step.key, step.tool, step.output || "");
      if (unavailable) return unavailable;
      const words = toolStepWords(step.tool);
      const name = words ? words.charAt(0).toUpperCase() + words.slice(1) : "A tool";
      if (step.remedy) return remedyRefusal(step.key, name, step.output || "", step.remedy);
      const refusal = policyRefusal(step.key, name, step.output || "");
      if (refusal) return refusal;
      const summary = shorten(step.output || "");
      return { id: step.key, text: summary ? `${name} failed: ${summary}` : `${name} failed` };
    });
  return { label, count, running, failures };
}
