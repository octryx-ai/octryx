// The run history lines from its events: phases, review rounds, decisions (person or platform) and the end.
import {
  ALLOWED_BY_DEFAULT_EVENT, TOOL_DENIED_EVENT, allowedByDefaultLine, sameAllowedByDefault, toolDeniedLine,
} from "./allowedByDefaultModel";
import type { Remedy } from "../devices/remedyModel";
import { documentationLine, type RunHistoryLink } from "./documentationEventsModel";
import type { StatusTone } from "../../layout/StatusLabel";
import { WORKFLOW_RUNS_PATH } from "./workflowRunRequests";
import { type RunNode } from "./workflowRunTypes";

// ---- How this run went (run card mock) ----------------------------------------------------------
// The run's history from its events: where it went on by itself (auto-accepted, auto-revised) is a quiet grey label
// with the reason, never a decision card, so the person sees where they were not asked and why.

export type RunEvent = {
  id: string;
  kind: string;
  node_id: string | null;
  detail: Record<string, unknown> | null;
  actor_id: string | null;
  created_at: string | null;
};
// A person's decision on the run (events endpoint `decisions`); `approval_id` when an approval carried it.
export type RunDecision = {
  id: string;
  node_id: string | null;
  action: string;
  approval_id: string | null;
  decided_by: string | null;
};
export type RunAutoLabel = "Auto-accepted" | "Auto-revised" | "Open findings" | "Needs a look";
export type RunHistoryEntry = {
  id: string;
  time: string;
  title: string;
  auto: RunAutoLabel | null;
  text: string;
  // The label's tone: neutral for the platform's routine steps, attention where a person still has to decide.
  tone?: StatusTone;
  // A secondary line under the text (the platform's own reason).
  note?: string;
  // The run went on with open review findings here: the run card lists them under this line.
  findings?: boolean;
  // The approval this decision was taken on: the line links to its detail page.
  approvalId?: string;
  // A documentation event's page (external) or the Documentation target card to fix a skip.
  link?: RunHistoryLink;
  // A routine line in muted text (a tool call only a Workspace default allowed).
  quiet?: boolean;
  // A refused tool call's one-click fix ("Allow in this Workspace").
  remedy?: Remedy;
};

/** "Continued with 3 open findings (1 high) — decide on the PR" (on_open_high: continue_with_findings). */
export function openFindingsEventText(detail: Record<string, unknown> | null | undefined): string {
  const findings = Math.max(0, Number(detail?.findings) || 0);
  const high = Math.max(0, Number(detail?.high) || 0);
  const count = `${findings} open finding${findings === 1 ? "" : "s"}`;
  return `Continued with ${count}${high ? ` (${high} high)` : ""} — decide on the PR`;
}

export function runEventsPath(runId: string): string {
  return `${WORKFLOW_RUNS_PATH}/${encodeURIComponent(runId)}/events`;
}

/** "09:24" in the viewer's time zone; "" without a time. */
export function clockTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}`;
}

function sentence(text: unknown): string {
  const value = String(text ?? "").trim();
  return value ? value[0].toUpperCase() + value.slice(1) : "";
}

const DECIDED: Record<string, string> = {
  confirmed: "confirmed",
  changed: "answered, another round",
  stopped: "stopped",
  approved: "approved",
  rejected: "rejected",
};

const ENDED: Record<string, string> = {
  completed: "Run finished",
  stopped: "Run stopped",
  failed: "Run failed",
  paused: "Run paused",
};

/** The run's history, oldest first: phases started, review rounds, decisions (a person's or the platform's), the end. */
export function runHistory(
  events: RunEvent[] | null | undefined,
  nodes: RunNode[] | null | undefined,
  formatTime: (iso: string | null | undefined) => string = clockTime,
  decisions: RunDecision[] | null | undefined = null,
  projectId: string | null = null,
): RunHistoryEntry[] {
  // A decision event and its decision record are written together (same node, action and person), in order.
  const unmatched = [...(decisions ?? [])];
  const approvalOf = (event: RunEvent, action: string): string | undefined => {
    const index = unmatched.findIndex((decision) => decision.node_id === event.node_id && decision.action === action
      && decision.decided_by === event.actor_id);
    if (index < 0) return undefined;
    const [decision] = unmatched.splice(index, 1);
    return decision.approval_id || undefined;
  };
  const titles = new Map((nodes ?? []).map((node) => [node.id, node.title || node.id]));
  const titleOf = (nodeId: string | null, fallback: string) => (nodeId && titles.get(nodeId)) || fallback;
  const entries: RunHistoryEntry[] = [];
  let rounds = 0;
  // The open "Allowed by default" row: equal calls in a row fold into it ("· 3 times").
  let allowed: { detail: Record<string, unknown>; times: number; index: number } | null = null;
  for (const event of events ?? []) {
    const detail = event.detail ?? {};
    const base = { id: event.id, time: formatTime(event.created_at), auto: null };
    if (event.kind === ALLOWED_BY_DEFAULT_EVENT) {
      if (allowed && allowed.index === entries.length - 1 && sameAllowedByDefault(allowed.detail, detail)) {
        allowed.times += 1;
        entries[allowed.index] = { ...entries[allowed.index], ...allowedByDefaultLine(detail, allowed.times) };
      } else {
        allowed = { detail, times: 1, index: entries.length };
        entries.push({ ...base, ...allowedByDefaultLine(detail) });
      }
      continue;
    }
    if (event.kind === TOOL_DENIED_EVENT) {
      entries.push({ ...base, ...toolDeniedLine(detail) });
      continue;
    }
    const documentation = documentationLine(event.kind, detail, projectId);
    if (documentation) {
      const { link, ...line } = documentation;
      entries.push({ ...base, ...line, ...(link ? { link } : {}) });
      continue;
    }
    if (event.kind === "auto_accepted") {
      entries.push({
        ...base,
        title: titleOf(event.node_id, "Decision"),
        auto: "Auto-accepted",
        text: sentence(detail.reason) || "Everything the platform checks passed",
      });
    } else if (event.kind === "accepted_with_open_findings") {
      entries.push({
        ...base,
        title: titleOf(event.node_id, "Decision"),
        auto: "Open findings",
        tone: "attention",
        text: openFindingsEventText(detail),
        note: sentence(detail.reason),
        findings: true,
      });
    } else if (event.kind === "auto_revised") {
      const revision = Number(detail.revision) || null;
      entries.push({
        ...base,
        title: titleOf(event.node_id, "Decision"),
        auto: "Auto-revised",
        text: `${revision ? `Revision ${revision}: the` : "The"} agent fixes the review's findings on its own`,
      });
    } else if (event.kind === "review_verdict") {
      rounds += 1;
      const findings = Number(detail.findings) || 0;
      const verdict = detail.verdict === "pass" ? "ready to ship"
        : detail.verdict === "changes" ? "changes needed" : String(detail.verdict ?? "no verdict");
      entries.push({
        ...base,
        title: `Review round ${rounds}`,
        text: `${verdict}${findings ? ` · ${findings} finding${findings === 1 ? "" : "s"}` : ""}`,
      });
    } else if (event.kind === "decision" && event.actor_id && detail.action) {
      // The platform's own decisions (no actor) are shown by their auto_accepted / accepted_with_open_findings /
      // auto_revised event.
      const approvalId = approvalOf(event, String(detail.action));
      entries.push({
        ...base, title: titleOf(event.node_id, "Decision"), text: DECIDED[String(detail.action)] ?? String(detail.action),
        ...(approvalId ? { approvalId } : {}),
      });
    } else if (event.kind === "node_entered" && detail.kind === "phase") {
      const round = Number(detail.iteration) || 0;
      entries.push({ ...base, title: titleOf(event.node_id, "Phase"), text: round > 1 ? `started, round ${round}` : "started" });
    } else if (event.kind === "run_started") {
      entries.push({ ...base, title: "Run", text: "started" });
    } else if (ENDED[event.kind]) {
      const outcome = event.kind === "completed" && detail.outcome ? String(detail.outcome) : "";
      entries.push({ ...base, title: ENDED[event.kind], text: outcome });
    }
  }
  return entries;
}

/** How often the platform sent the work back on its own before the person was asked ("" for none). */
export function autoRevisedText(events: RunEvent[] | null | undefined): string {
  const count = (events ?? []).filter((event) => event.kind === "auto_revised").length;
  if (!count) return "";
  return `The agent revised ${count === 1 ? "once" : `${count} times`} on its own before you were asked`;
}
