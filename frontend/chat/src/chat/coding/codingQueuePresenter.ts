import type { CodingSessionSummary } from "./codingTypes";
import { validationLabel } from "./codingEvidenceModel";
import { blockerCountText, reviewSummaryLabel } from "./codingReviewSummary";

// Queue semantics and copy for the Coding cockpit (audit IDs 26, 27, 32, 33):
// every queue explains what it contains, when items appear and the next step,
// instead of one generic cockpit text.
// "sessions" is All; the queues are the filter tabs of Coding → Sessions.
export type CodingQueueKey = "sessions" | "running" | "review" | "blocked" | "completed";

export const CODING_QUEUE_KEYS: readonly CodingQueueKey[] = ["sessions", "running", "review", "blocked", "completed"];

export const ATTENTION_SESSION_STATES: ReadonlySet<string> = new Set([
  "blocked",
  "needs_replan",
  "needs_human_review",
  "changes_requested",
]);
const REVIEW_SESSION_STATES: ReadonlySet<string> = new Set(["review_ready", "pr_open"]);
const RUNNING_SESSION_STATES: ReadonlySet<string> = new Set(["implementing", "testing"]);

export const WORK_AREA_HREF = "/chat?area=work";

export type CodingQueueEmptyAction =
  | { kind: "startSession"; label: string }
  | { kind: "clearSearch"; label: string }
  | { kind: "openQueue"; label: string; queue: CodingQueueKey }
  | { kind: "link"; label: string; href: string };

export type CodingQueueEmptyContent = {
  eyebrow: string;
  title: string;
  body: string;
  actions: CodingQueueEmptyAction[];
};

export function isCodingQueue(value: string): value is CodingQueueKey {
  return (CODING_QUEUE_KEYS as readonly string[]).includes(value);
}

export function sessionInQueue(session: Pick<CodingSessionSummary, "state">, queue: CodingQueueKey): boolean {
  if (queue === "sessions") return true;
  if (queue === "running") return RUNNING_SESSION_STATES.has(session.state);
  if (queue === "review") return REVIEW_SESSION_STATES.has(session.state);
  if (queue === "blocked") return ATTENTION_SESSION_STATES.has(session.state);
  return session.state === "completed";
}

export function codingQueueEmptyState(
  queue: CodingQueueKey,
  // unavailableReviewCount: sessions without a current work review verdict; one of them may
  // hide a requested change, so an empty Blocked queue is then only "no known blocked session".
  context: { queueCount: number; workItemCount: number; search: string; unavailableReviewCount?: number },
): CodingQueueEmptyContent {
  const search = context.search.trim();
  if (context.queueCount > 0 && search) {
    return {
      eyebrow: "No matches",
      title: `No coding session in this queue matches "${search}".`,
      body: "The search looks at work item keys, titles, repositories and branches. Clear it to see the whole queue.",
      actions: [{ kind: "clearSearch", label: "Clear search" }],
    };
  }
  if (queue === "sessions") return cockpitEmptyState(context.workItemCount);
  if (queue === "running") {
    return {
      eyebrow: "Running",
      title: "No coding session is running.",
      body: "A session appears here while the agent implements or tests a change.",
      actions: [{ kind: "openQueue", label: "Open all sessions", queue: "sessions" }],
    };
  }
  if (queue === "review") {
    return {
      eyebrow: "Review queue",
      title: "No coding session is waiting for review.",
      body:
        "A session appears here when its code is ready for review or its pull request is open (Work → Pull requests). " +
        "Plans waiting for a reviewer's decision are listed under Work → Plans · Waiting for review.",
      actions: [
        { kind: "openQueue", label: "Open all sessions", queue: "sessions" },
        { kind: "link", label: "Open Work", href: WORK_AREA_HREF },
      ],
    };
  }
  const unavailable = context.unavailableReviewCount || 0;
  if (queue === "blocked" && unavailable > 0) {
    const sessions = `${unavailable} coding session${unavailable === 1 ? " has" : "s have"}`;
    return {
      eyebrow: "Blocked queue",
      title: "No known blocked coding session.",
      body:
        `${sessions} no current work review verdict, so requested changes may not be counted here. Open the ` +
        "cockpit, select a session whose work review is unavailable and use Retry in its overview.",
      actions: [{ kind: "openQueue", label: "Open all sessions", queue: "sessions" }],
    };
  }
  if (queue === "blocked") {
    return {
      eyebrow: "Blocked queue",
      title: "No coding session is blocked.",
      body:
        "A session appears here when it needs a person: a failed check or preflight blocker, requested changes, a Jira " +
        "change after the plan was approved, or stale source evidence. Open the session to see the blocker, then " +
        "resolve it on the work item in Work or by creating a new change plan.",
      actions: [{ kind: "openQueue", label: "Open all sessions", queue: "sessions" }],
    };
  }
  return {
    eyebrow: "History",
    title: "No coding session is completed yet.",
    body:
      "Completed sessions are the history of finished work: the work item is done or closed. Each keeps its " +
      "change plan, evidence, checks and audit trail for later review.",
    actions: [{ kind: "openQueue", label: "Open all sessions", queue: "sessions" }],
  };
}

function cockpitEmptyState(workItemCount: number): CodingQueueEmptyContent {
  if (workItemCount === 0) {
    return {
      eyebrow: "Get started",
      title: "No work items to code on yet.",
      body:
        "Coding works on work items imported in Work. Work plans and reviews a task; Coding carries it out. Import " +
        "work items in Work → Intake, then start a coding session here.",
      actions: [{ kind: "link", label: "Open Work", href: WORK_AREA_HREF }],
    };
  }
  const items = `${workItemCount} work item${workItemCount === 1 ? " is" : "s are"}`;
  return {
    eyebrow: "Sessions",
    title: "No coding session yet.",
    body:
      `A coding session takes one work item from a change plan through implementation and checks to a pull request. ` +
      `${items} available. A work item also appears here once its Jira issue carries the coding trigger label set ` +
      `in its intake (Work → Intake).`,
    actions: [{ kind: "startSession", label: "Start coding session" }],
  };
}

// What the filter tabs do not say, as one short line, and only when it is true: how many
// sessions wait for a plan, and that an unreadable work review may hide a blocked session.
export function codingSessionsNote(
  sessions: Array<Pick<CodingSessionSummary, "state" | "phase"> & Partial<Pick<CodingSessionSummary, "review">>>,
): string | null {
  const ready = sessions.filter((session) => session.phase === "ready_to_plan").length;
  const unknownReviews = sessions.filter((session) => session.review?.status === "unavailable").length;
  const parts = [
    ready ? `${ready} waiting for a plan` : "",
    unknownReviews
      ? `${unknownReviews} work review${unknownReviews === 1 ? "" : "s"} unavailable, so Blocked may miss a session`
      : "",
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : null;
}

/** The facts a session card does not show, as its tooltip. */
export function sessionCardFacts(session: CodingSessionSummary): string {
  return [
    session.repositories[0] || "Repository not planned yet",
    blockerCountText(session.blockerCount, session.review),
    `${session.recordedEvidenceCount} recorded evidence`,
    `${session.pullRequests.length} PRs`,
    validationLabel(session.validation),
    reviewSummaryLabel(session.review),
  ].join(" · ");
}
