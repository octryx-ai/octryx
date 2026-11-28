import type { AttentionAction, AttentionItem, AttentionKind, RunState } from "./companionTypes";

export const KIND_LABEL: Record<AttentionKind, string> = {
  question: "Question", gate: "Approval", device_approval: "Device approval", done: "Finished",
  problem: "Problem", budget: "Budget", allowance: "Allowance", handover: "Handover",
  live: "Session answered", turn: "Mac turn", pool: "Session pool",
};

export const RUN_STATE_LABEL: Record<RunState, string> = { working: "Working", needs_you: "Needs you", done: "Finished", problem: "Problem" };

const TERMS: Record<string, string> = {
  ask: "Approval", approval: "Approval", contract: "Test contract to confirm", test_contract: "Test contract to confirm",
  done: "Finished", completed: "Finished", finished: "Finished", merged: "Merged", pr_open: "Waiting for merge",
  waiting_merge: "Waiting for merge", awaiting_merge: "Waiting for merge", delivered: "Delivered", stopped: "Stopped",
  failed: "Failed", aborted: "Aborted", clarify: "Clarify", implement: "Implement", review: "Review",
};

const MERGE_WAITS = ["merged", "merge", "pr_open", "waiting_merge", "awaiting_merge", "watching", "watch"];

export const WAITING_SENTENCE: Record<string, string> = {
  awaiting_confirmation: "Waiting for your confirmation",
  watching: "Waiting for merge", watch: "Waiting for merge", merged: "Waiting for merge", merge: "Waiting for merge",
  awaiting_approval: "Waiting for approval", waiting_approval: "Waiting for approval",
  allowed_awaiting_approval: "Waiting for approval", approval: "Waiting for approval",
  awaiting_tool_approval: "Waiting for a tool approval",
  awaiting_answer: "Waiting for your answer", question: "Waiting for your answer",
  waiting_for_reply: "Waiting for a reply",
  awaiting_review: "Waiting for review", waiting_review: "Waiting for review",
  device: "Waiting for the device", awaiting_device: "Waiting for the device", waiting_for_device: "Waiting for the device",
  ci: "Waiting for checks", checks: "Waiting for checks",
  schedule: "Waiting for its schedule",
  awaiting_subagents: "Waiting for helper agents", waiting_children: "Waiting for helper agents",
  sub_workflow: "Waiting for a sub-workflow",
  handoff: "Waiting for a handover", handover: "Waiting for a handover",
  functional_acceptance: "Waiting for the functional sign-off",
  audience_receipt: "Waiting for the audience to confirm receipt",
};

export const PAUSE_REASON: Record<string, string> = {
  acceptance_timeout: "acceptance took too long", action_failed: "an action failed",
  approval_timeout: "the approval took too long", audience_unproven: "receipt was not confirmed",
  budget_limit: "the budget limit was reached", checks_failed: "the checks stayed red",
  content_blocked: "content was blocked",
  documentation_missing: "documentation is missing", environment_not_ready: "the environment is not ready",
  evidence_unresolved: "evidence is unresolved", loop_limit: "the loop limit was reached",
  needs_approval: "a change needs approval",
  needs_configuration: "something needs configuration", no_reply: "no reply came",
  publish_unverified: "publishing was not verified", review_no_decision: "the review made no decision",
  runtime_failed: "the run location failed", watch_timeout: "waiting for merge took too long",
  workspace_dirty: "the folder has uncommitted changes",
  emergency_stop: "stopped by emergency stop",
  loop_detected: "paused automatically after a loop",
};

export function waitingSentence(waitingKind: string): string {
  return WAITING_SENTENCE[waitingKind.trim().toLowerCase()] ?? "Waiting";
}

export function pausedSentence(pauseReason: string): string {
  const reason = PAUSE_REASON[pauseReason.trim().toLowerCase()];
  return reason ? `Paused: ${reason}` : "Paused";
}

export function runStatePhrase(status: string, node: string, waitingKind: string, fallback: string, pauseReason = ""): string {
  const lowered = status.trim().toLowerCase();
  if (lowered !== "waiting" && lowered !== "paused") return fallback;
  // A finished run or a run in problem keeps its word; only a "working" or "needs you" reading is refined.
  if (fallback && fallback !== RUN_STATE_LABEL.working && fallback !== RUN_STATE_LABEL.needs_you) return fallback;
  if (lowered === "paused") return pausedSentence(pauseReason);
  const wait = waitingKind.trim().toLowerCase();
  if (WAITING_SENTENCE[wait]) return WAITING_SENTENCE[wait];
  if (MERGE_WAITS.includes(node.trim().toLowerCase()) || wait.includes("merge")) return "Waiting for merge";
  return "Waiting";
}

export function runName(ticketKey: string, title: string, fallback: string): string {
  const name = [ticketKey.trim(), title.trim()].filter(Boolean).join(" ");
  return name || fallback;
}

export function humanize(value: string): string {
  const raw = value.trim();
  if (!raw) return "";
  const known = TERMS[raw.toLowerCase()];
  if (known) return known;
  const spaced = raw.replace(/[_.-]+/g, " ").replace(/\s+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function stripMarkdown(text: string): string {
  return text
    .replace(/!\[[^\]]*\]\([^)]*\)/g, "")
    .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
    .replace(/`([^`]*)`/g, "$1")
    .replace(/\*\*(.+?)\*\*/g, "$1")
    .replace(/\*(.+?)\*/g, "$1")
    // Underscore emphasis only at word edges, so snake_case names stay intact.
    .replace(/(^|[^\w])__?(.+?)__?(?=[^\w]|$)/g, "$1$2")
    .replace(/^\s{0,3}(#{1,6}|>|[-*+]|\d+\.)\s+/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

export function firstSentence(text: string, max = 120): string {
  const plain = stripMarkdown(text);
  const match = /^(.+?[.?!])(\s|$)/.exec(plain);
  const sentence = (match ? match[1] : plain).trim();
  return sentence.length > max ? `${sentence.slice(0, max - 1).trimEnd()}…` : sentence;
}

export function itemTitle(item: AttentionItem): string {
  const title = stripMarkdown(item.title);
  const text = stripMarkdown(item.text);
  if (!title || (text && (title === text || text.startsWith(title) || title.length > 120))) return firstSentence(item.title || item.text);
  return firstSentence(title);
}

export function subtitleText(item: AttentionItem): string {
  const raw = item.subtitle.trim();
  if (!raw) return "";
  return /^[a-z0-9_.-]+$/.test(raw) ? humanize(raw) : raw;
}

const FINISHED = /^Finished \(([^)]*)\)\.?\s*/;

export function itemText(item: AttentionItem): string {
  const finished = FINISHED.exec(item.text);
  if (!finished) return item.text;
  const outcome = finished[1].trim().toLowerCase();
  const head = outcome === "merged" ? "Finished and merged."
    : ["pr_open", "waiting_merge", "awaiting_merge"].includes(outcome) ? "Finished; waiting for merge."
      : outcome && !["done", "completed", "finished"].includes(outcome) ? `Finished: ${humanize(outcome)}.` : "Finished.";
  const rest = item.text.slice(finished[0].length).trim();
  return rest ? `${head} ${rest}` : head;
}

export function cardParts(item: AttentionItem, title: string): { subtitle: string; meta: string[]; body: string } {
  let body = itemText(item);
  let subtitle = subtitleText(item);
  const says = (text: string, word: string) => Boolean(text) && text.toLowerCase().includes(word.toLowerCase());
  const same = (a: string, b: string) => {
    const plain = (text: string) => stripMarkdown(text).replace(/[.!?:]+$/, "").trim().toLowerCase();
    return Boolean(a) && Boolean(b) && plain(a) === plain(b);
  };
  const kind = item.sample ? "Sample run" : KIND_LABEL[item.kind];
  if (same(body, title)) body = "";
  if (item.kind === "done" && /^finished\.?$/i.test(body) && (says(title, "finished") || says(subtitle, "finished"))) body = "";
  if (same(subtitle, title) || same(subtitle, body)) subtitle = "";
  const kindShown = !(says(title, kind) || says(subtitle, kind) || says(body, kind));
  return { subtitle, meta: [kindShown ? kind : "", item.workspace?.name ?? "", item.workItem?.key ?? ""].filter(Boolean), body };
}

// Stop and abort end a run: always in the ⋯ menu, never the visible decision.
const MENU_KEYS = new Set(["stop", "abort", "cancel", "emergency_stop"]);
const ENDED: AttentionKind[] = ["done"];

export type CardActions = { decisions: AttentionAction[]; menu: AttentionAction[] };

export function cardActions(item: AttentionItem): CardActions {
  const seen = new Set<string>();
  const unique = item.actions.filter((action) => {
    const id = `${action.key}|${action.request.method}|${action.request.path}|${JSON.stringify(action.request.body)}`;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  }).map((action) => (action.key === "dismiss" ? { ...action, label: "Dismiss", tone: "neutral" as const } : action));
  const ended = ENDED.includes(item.kind);
  const isMenu = (action: AttentionAction) => MENU_KEYS.has(action.key) || action.tone === "danger";
  return {
    decisions: unique.filter((action) => !isMenu(action)),
    menu: ended ? [] : unique.filter(isMenu),
  };
}

export function targetPhrase(target: { kind: string; label: string; online: boolean | null } | null): string {
  if (!target?.label && target?.kind !== "server") return "";
  const label = target.kind === "server" || /^the server$/i.test(target.label) ? "the server" : target.label;
  return `on ${label}${target.online === false ? " · offline" : ""}`;
}
