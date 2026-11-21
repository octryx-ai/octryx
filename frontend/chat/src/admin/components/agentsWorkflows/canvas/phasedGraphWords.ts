// Phased workflow graph: node families, action and condition words, edge tones, labels and box subtitles.
import { modelDisplayName } from "../../../../chat/header/runDetailsFacts";
import type { PhasedEdge, PhasedNode } from "./phasedWorkflowModel";
import type { EdgeTone, GraphBox, NodeFamily } from "./phasedGraphTypes";

export const FAMILY_LABELS: Record<NodeFamily, string> = {
  start: "Start",
  agent: "Agent phase",
  parallel: "Parallel work",
  action: "Platform action",
  person: "Person decides",
  wait: "Waits",
  check: "Check",
  decision: "Decision",
  subflow: "Sub-workflow",
  end: "End",
};

const KIND_FAMILY: Record<string, NodeFamily> = {
  start: "start",
  phase: "agent",
  review: "agent",
  parallel_work: "parallel",
  platform_action: "action",
  user_confirmation: "person",
  user_conversation: "person",
  approval: "person",
  pause: "person",
  watch: "wait",
  gate: "check",
  decision: "decision",
  sub_workflow: "subflow",
  outcome: "end",
};

export const KIND_LABELS: Record<string, string> = {
  review: "Independent review",
  user_confirmation: "User confirms",
  user_conversation: "Ask the user",
  approval: "Approval",
  pause: "Paused for the requester",
  watch: "Waits for",
};

export function nodeFamily(kind: string): NodeFamily {
  return KIND_FAMILY[kind] ?? "check";
}

export function familyLabel(family: NodeFamily): string {
  return FAMILY_LABELS[family];
}

const words = (value: string) => value.replace(/[._]+/g, " ").trim();

// Platform actions in plain words; an unknown one reads as its code in words.
const ACTION_WORDS: Record<string, string> = {
  "jira.create_issue": "Creates the Jira issue",
  "work.create_stories": "Creates the planned stories",
  "jira.transition": "Moves the Jira issue",
  "jira.comment": "Comments on the Jira issue",
  "scm.create_branch": "Creates a branch",
  "scm.push": "Pushes the commits",
  "scm.open_pr": "Opens a pull request",
  "scm.merge_pr": "Merges the pull request",
  "workspace.prepare": "Prepares the working folder",
};

export function actionWords(action: string | undefined): string {
  if (!action) return "Calls a platform tool";
  return ACTION_WORDS[action] ?? `Runs ${words(action)}`;
}

// The closed values an exit routes on, as a reader says them.
const WHEN_WORDS: Record<string, string> = {
  succeeded: "succeeded",
  failed: "failed",
  passed: "passed",
  confirmed: "confirmed",
  changed: "changes asked",
  stopped: "stopped",
  approved: "approved",
  rejected: "rejected",
  accepted: "accepted",
  not_testable_yet: "not testable yet",
  "ci.succeeded": "CI green",
  "ci.failed": "CI red",
  "pr.merged": "merged",
  "pr.declined": "declined",
  "pr.approved": "PR approved",
  "jira.status": "Jira status changed",
  "approval.decided": "decided",
  delivered: "delivered",
  done: "done",
  blocked: "blocked",
};

export function whenWords(when: string | null | undefined): string {
  if (!when) return "";
  return WHEN_WORDS[when] ?? words(when);
}

const FAILURE_WHENS = new Set(["failed", "rejected", "stopped", "ci.failed", "pr.declined", "blocked"]);
export const SUCCESS_WHENS = new Set([
  "succeeded", "passed", "approved", "confirmed", "accepted", "ci.succeeded", "pr.merged", "delivered", "done",
]);
export const GOOD_OUTCOMES = new Set(["done", "delivered"]);

function isErrorPath(node: PhasedNode): boolean {
  return node.kind === "pause" || (node.kind === "outcome" && !GOOD_OUTCOMES.has(node.outcome ?? ""));
}

// The boxes where a person decides: drawn even on the error path.
export const HUMAN_KINDS = new Set(["user_conversation", "user_confirmation", "approval", "watch", "pause"]);

// An end that is only reached through failures (or from the pause after a failed step): a badge, not a box. An end
// a normal way leads to ("Waiting for clarification" after the questions were posted) is a box like any other.
export function isErrorEnd(node: PhasedNode, edges: PhasedEdge[], byId: Map<string, PhasedNode>): boolean {
  if (node.kind !== "outcome" || GOOD_OUTCOMES.has(node.outcome ?? "")) return false;
  const into = edges.filter((edge) => edge.kind !== "loop" && edge.target === node.id && byId.has(edge.source));
  return into.every((edge) => (edge.when && FAILURE_WHENS.has(edge.when)) || byId.get(edge.source)!.kind === "pause");
}

// A target in a badge: its title, or for a long one a short name ("on failure → Pause"); the tooltip says it all.
const SHORT_TITLE = 22;
export function shortTitle(box: Pick<GraphBox, "title" | "kind">): string {
  if (box.title.length <= SHORT_TITLE) return box.title;
  if (box.kind === "pause") return "Pause";
  return `${box.title.slice(0, SHORT_TITLE - 2).trimEnd()}…`;
}

export function edgeTone(edge: Pick<PhasedEdge, "kind" | "when">, target?: PhasedNode): EdgeTone {
  if (edge.kind === "loop") return "loop";
  if (edge.when && FAILURE_WHENS.has(edge.when)) return "failure";
  if (target && isErrorPath(target)) return "failure";
  if (edge.when && SUCCESS_WHENS.has(edge.when)) return "success";
  return "neutral";
}

// "failed → retry (max 3)" on a loop; the route word on a forward exit; nothing on a plain "then".
export function edgeLabel(edge: Pick<PhasedEdge, "kind" | "when" | "max_iterations">): string {
  const route = whenWords(edge.when);
  if (edge.kind === "loop") {
    const limit = edge.max_iterations ? ` (max ${edge.max_iterations})` : "";
    return `${route || "again"} → retry${limit}`;
  }
  return route;
}

function count(value: number | undefined, one: string, many: string): string {
  const n = value ?? 0;
  return `${n} ${n === 1 ? one : many}`;
}

// The one line under a box's title: only what the title and the kind do not already say.
export function boxSubtitle(node: PhasedNode): string {
  switch (node.kind) {
    case "phase": {
      const agent = typeof node.agent === "string" && node.agent ? node.agent : "no agent set";
      // The phase's own model when it sets one ("engineer · Claude Sonnet 5.5 · 1 check"): role boxes that share an
      // agent profile differ by model.
      const model = typeof node.config?.model === "string" && node.config.model.trim() ? modelDisplayName(node.config.model) : "";
      return [agent, model, count(node.checks, "check", "checks")].filter(Boolean).join(" · ");
    }
    case "parallel_work": {
      // Which roles the coordinator's plan may use; how many items is decided per run.
      const roles = node.config?.roles && typeof node.config.roles === "object" ? Object.keys(node.config.roles) : [];
      return `${roles.length ? roles.join(" · ") : "no roles set"} — split at run time`;
    }
    case "platform_action":
      return node.action ? actionWords(node.action) : node.tool ? `Runs ${words(node.tool)}` : "";
    case "gate":
      return count(node.checks, "check", "checks");
    case "user_confirmation":
      return node.subject ? `Confirms the ${words(node.subject)}` : "";
    case "user_conversation":
      return node.question ?? "";
    case "pause":
      return "Retry, change or abort";
    case "watch":
      return (node.conditions ?? []).map(whenWords).join(" or ");
    case "sub_workflow":
      return node.workflow_key ? `Runs ${node.workflow_key}` : "";
    case "outcome":
      return node.outcome && node.outcome !== "done" ? `Run ends: ${words(node.outcome)}` : "";
    default:
      return "";
  }
}

const STOP_WORDS = new Set(["a", "an", "the", "of", "or", "and", "to", "for", "on", "in", "run", "ends", "runs"]);
const wordSet = (value: string) => value.toLowerCase().split(/[^a-z0-9]+/)
  .filter((word) => word && !STOP_WORDS.has(word)).map((word) => word.replace(/(ed|s)$/, ""));

// A line that only repeats the title or the kind ("Confirms the reproduction" under "Confirm the reproduction").
export function repeats(line: string, ...said: string[]): boolean {
  const known = new Set(said.flatMap(wordSet));
  const own = wordSet(line);
  return own.every((word) => known.has(word));
}
