// The chat's view of a workflow run. The server decides everything: the
// run's state, which actions the viewer has and what they need. This module only turns the payload into
// display text and the request an action posts.

import type { RunNodeFragment, WorkflowRun, RunRow, RunRouting } from "./workflowRunTypes";

// "Phase 2 of 4 · Implement" for a run whose cursor is on a phase; the node title otherwise. A node from a
// fragment adds where it came from: "Reserve publication · sf-publish-prove v1".
export function runPositionText(run: WorkflowRun): string {
  const node = run.current_node;
  if (!node) return "";
  const { index, total } = run.phase_position;
  const text = node.kind === "phase" && index && total ? `Phase ${index} of ${total} · ${node.title}` : node.title;
  return node.fragment ? `${text} · ${runFragmentText(node.fragment)}` : text;
}

export function runFragmentText(fragment: RunNodeFragment): string {
  return fragment.version ? `${fragment.key} v${fragment.version}` : fragment.key;
}

export function runLoopTexts(run: WorkflowRun): string[] {
  return run.loops
    .filter((loop) => loop.limit > 0)
    .map((loop) => `${loop.title} ${loop.used}/${loop.limit}`);
}

export function runGateText(run: WorkflowRun): string {
  const gate = run.gate;
  if (!gate || !gate.state) return "";
  const failed = (gate.results ?? []).filter(
    (item) => item.outcome === "failed" && item.blocking,
  );
  if (gate.state === "passed") return "Checks passed";
  if (!failed.length) return `Checks: ${gate.state.replace(/_/g, " ")}`;
  return `Open checks: ${failed.map((item) => item.description || item.type).join("; ")}`;
}

type RunRefreshFacts = {
  selectedMessages?: { id: string }[] | null;
  selectedApprovals?: { id: string; status: string }[] | null;
} | null | undefined;

// The run bar reloads on a new message, an approval change or a turn start/end; not on the live activity line,
// which changed several times per turn and reloaded the run each time (perf audit).
export function runRefreshKey(state: RunRefreshFacts, running: boolean): string {
  const messages = state?.selectedMessages ?? [];
  const pending = (state?.selectedApprovals ?? [])
    .filter((approval) => approval.status === "pending")
    .map((approval) => approval.id)
    .join(",");
  return `${messages.length}:${messages.at(-1)?.id ?? ""}:${pending}:${running ? "running" : "idle"}`;
}

export function runStopText(
  run: Pick<WorkflowRun, "stop"> | Pick<RunRow, "stop_reason">,
): string | null {
  const reason = "stop" in run ? run.stop?.reason : "stop_reason" in run ? run.stop_reason : null;
  return reason ? `Stopped: ${reason}` : null;
}

const ADOPTED_LABELS: Record<string, string> = {
  branch: "Branch",
  ticket: "Ticket",
  change_plan: "Change plan",
  pull_request: "Pull request",
};

// "Branch taken over from run …": provenance of what this run adopted from earlier runs of its Work item.
export function runAdoptedTexts(run: Pick<WorkflowRun, "adopted">): string[] {
  return Object.entries(run.adopted ?? {}).map(([kind, facts]) => {
    const runs = Array.isArray(facts.from_runs) ? facts.from_runs.map(String) : [String(facts.from_run ?? "")];
    const by = facts.decided_by ? " (your decision)" : "";
    const base = String(facts.base_branch ?? "the default branch");
    const behind = typeof facts.behind_base === "number" && facts.behind_base > 0
      ? ` · ${facts.behind_base} commit${facts.behind_base === 1 ? "" : "s"} behind ${base} (not moved: it has its own commits)`
      : "";
    const forwarded = facts.fast_forwarded_from ? ` · fast-forwarded to the current ${base}` : "";
    return `${ADOPTED_LABELS[kind] ?? kind} taken over from run ${runs.filter(Boolean).join(", ")}${by}${forwarded}${behind}`;
  });
}

export function chatSessionHref(sessionId: string): string {
  return `/chat?session_id=${encodeURIComponent(sessionId)}`;
}

export const INSTALL_LAUNCHER_HREF = "/chat?area=agents&agents_view=install";
export const FOLLOW_UP_NOT_STARTED = "Follow-up not started";

/** A triage's follow-up that did not start (fresh-clone run: it was silent): what to show, and whether the
 *  way out is a device (the server refuses to build or test). Null when the follow-up started or there is none. */
export function followUpFailure(
  run: { routing?: RunRouting | null; follow_up_failed?: RunRow["follow_up_failed"] } | null | undefined,
): { text: string; needsDevice: boolean } | null {
  const failed = run?.routing?.state === "failed" ? run.routing : run?.follow_up_failed;
  if (!failed) return null;
  const workflow = failed.workflow_key ? `"${failed.workflow_key}"` : "the follow-up workflow";
  const reason = (failed.message ?? "").trim();
  return {
    text: `The triage is done, but ${workflow} did not start${reason ? `: ${reason}` : "."}`,
    needsDevice: failed.code === "server_build_not_allowed",
  };
}
export const SAMPLE_RUN_LABEL = "Sample run";
export const SAMPLE_RUN_TEXT =
  "A sample run: a real run recorded on another install and imported into this demo.";

/** The "Sample run" badge of an imported sample run, null for every other run. */
export function sampleRunBadge(run: { sample?: boolean } | null | undefined): { label: string; title: string } | null {
  return run?.sample === true ? { label: SAMPLE_RUN_LABEL, title: SAMPLE_RUN_TEXT } : null;
}

/** Knowledge has exactly the published version (AFS-7): the backend's proof, bound to this page version — never a
 * bare ledger state. A withheld, unavailable or other-version item is not "in Knowledge". */
function provenInKnowledge(page: NonNullable<WorkflowRun["documentation"]>): boolean {
  const knowledge = page.knowledge;
  if (!knowledge || knowledge.in_knowledge !== true || knowledge.item_state !== "ingested") return false;
  if (page.version === null || page.version === undefined) return false;
  const published = String(page.version);
  return String(knowledge.version ?? "") === published && String(knowledge.page_version ?? "") === published;
}

/** The documentation page a run published (a link only to an http(s) page) and whether Knowledge has it. */
export function documentationView(
  run: Pick<WorkflowRun, "documentation">,
): { title: string; url: string | null; version: number | null; inKnowledge: boolean } | null {
  const page = run.documentation;
  if (!page || !page.url) return null;
  return {
    title: page.title || "Documentation",
    url: /^https?:\/\//.test(page.url) ? page.url : null,
    version: typeof page.version === "number" ? page.version : null,
    inKnowledge: provenInKnowledge(page),
  };
}

/** The requester's own review of the pull request they authored; a link only to an http(s) page. */
export function reviewerNoticeView(
  run: Pick<WorkflowRun, "reviewer_notice">,
): { text: string; url: string | null; linkAccount: boolean } | null {
  const notice = run.reviewer_notice;
  if (!notice || !notice.text) return null;
  // An unlinked requester account: the card links to Profile → Linked accounts.
  return { text: notice.text, url: /^https?:\/\//.test(notice.url) ? notice.url : null,
    linkAccount: Boolean(notice.link_account) };
}

// "312k tokens in · 24k out · 41 calls · $0.06" — the run's model spend, or "" before the first call.
export function runUsageText(usage: WorkflowRun["model_usage"]): string {
  if (!usage || !usage.calls) return "";
  const short = (value: number) => (value >= 1_000_000 ? (value / 1_000_000).toFixed(1) + "M"
    : value >= 1000 ? Math.round(value / 1000) + "k" : String(value));
  return [short(usage.tokens_in) + " tokens in", short(usage.tokens_out) + " out", usage.calls + " calls",
    "$" + usage.cost.toFixed(2)].join(" · ");
}

// Long phase and readiness answers (the backend does not cut them, up to 100k) fold on the card: the first lines show,
// the whole text opens on demand.
export const FOLD_AT = 1200;

/** The first ~12 lines (at most FOLD_AT characters) of a long answer, ending with "…". */
export function foldPreview(text: string): string {
  const head = text.split("\n").slice(0, 12).join("\n").slice(0, FOLD_AT);
  return `${head.trimEnd()}…`;
}

// The review bot's run has a session but no conversation: its review is posted on the pull request (fresh demo
// "Open the chat" opened "No messages yet."). Every other run's chat is where it happened.
const REVIEW_BOT_WORKFLOW = "pr-review-bot";

export function opensChat(run: Pick<RunRow, "workflow_key">): boolean {
  return run.workflow_key !== REVIEW_BOT_WORKFLOW;
}
