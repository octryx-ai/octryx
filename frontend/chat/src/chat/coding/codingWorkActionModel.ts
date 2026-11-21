import type { CodingSessionDetailData, CodingSessionSummary } from "./codingTypes";
import { latestByVersion, recordValue } from "./codingSessionValues";
import { PLAN_STATUS } from "../work/planStatus";

// Guided Coding-to-Work handoff: what a person must do in Work before Coding can continue,
// and where exactly. A plan-owned reason links the exact latest plan by `work_item_id` and
// `change_plan_id`; anything a plan does not resolve (runtime or source blockers) is listed as such
// and only gets the generic Work Item link. Guidance only: Start agent eligibility is unchanged.

// Session states that need a person in Work (the detail header shows "Work action required").
export const WORK_ACTION_STATES: ReadonlySet<string> = new Set(["blocked", "needs_replan", "needs_human_review"]);

// Plan statuses that need a person on the plan in Work. The wording names only what the Work plan
// view really offers: reading the plan and its open questions, a reviewer's "Approve vN" / "Clarify"
// / "Reject" on a plan that is not final, "New version", and on the newest open version with
// open questions one answer field per question plus "Generate v{n+1} from answers". There is no
// draft editor, so the guidance never promises one.
const PLAN_STATUS_GUIDANCE: Record<
  string,
  { title: (version: number) => string; message: string; action: string; startHint: (version: number) => string }
> = {
  [PLAN_STATUS.needsClarification]: {
    title: (version) => `Plan v${version} has open questions`,
    message:
      "Review the open questions in Work: they name missing context. Once the task, repository or reviewer " +
      "setup is corrected, create a new plan version there with New version; a reviewer then decides on it.",
    action: "Review open questions",
    startHint: (version) =>
      `Start agent needs an approved plan; it stays unavailable until plan v${version} or a newer version is approved.`,
  },
  [PLAN_STATUS.readyForReview]: {
    title: (version) => `Plan v${version} is waiting for a review decision`,
    message: "A reviewer approves the plan, asks for clarification or rejects it in Work.",
    action: "Review plan",
    startHint: (version) =>
      `Start agent needs an approved plan; it stays unavailable until plan v${version} or a newer version is approved.`,
  },
  [PLAN_STATUS.rejected]: {
    title: (version) => `Plan v${version} was rejected`,
    message:
      "A rejected plan cannot be approved. Review it in Work and, once the missing context is corrected, " +
      "create a new plan version there with New version.",
    action: "Open rejected plan",
    startHint: () => "Start agent stays unavailable until a new plan version is created and approved.",
  },
  [PLAN_STATUS.draft]: {
    title: (version) => `Plan v${version} is a draft`,
    message: "Review the plan in Work: a reviewer can decide on it there, or a new version can be created.",
    action: "Open draft plan",
    startHint: (version) =>
      `Start agent needs an approved plan; it stays unavailable until plan v${version} or a newer version is approved.`,
  },
};

// needs_clarification with recorded open questions: the exact latest plan is answerable in Work.
// Answers are requirements input only: they do not change repository, profile or reviewer
// setup, and the generated version still needs a reviewer's approval before Start agent.
const ANSWER_GUIDANCE = {
  message: (version: number) =>
    `Answer the open questions on plan v${version} in Work, then use Generate v${version + 1} from answers. ` +
    "Unanswered questions stay open in the new version, and a reviewer then decides on it. Answers do not " +
    "change repository or reviewer setup: correct that setup in Work first if a question depends on it.",
  action: "Answer open questions",
};

const MAX_LISTED = 5;
const TEXT_KEYS = ["message", "detail", "reason", "title", "summary", "question", "code"] as const;

export type CodingWorkAction = {
  // hidden: nothing to do in Work (startable, running or finished); checking: the detail is still
  // loading or belongs to another item, so no plan is named yet; plan: the exact plan resolves it;
  // item: no supported resolution target, so only the Work Item is offered.
  state: "hidden" | "checking" | "plan" | "item";
  title: string;
  message: string;
  // Why Start agent is unavailable (its policy is not changed here).
  startHint: string;
  planAction: { label: string; href: string } | null;
  workItemHref: string;
  // Open questions recorded on the exact plan.
  questions: ListedEntries;
  // Other recorded blockers; never presented as solved by the plan.
  blockers: ListedEntries;
};

export type ListedEntries = { shown: string[]; more: number; unreadable: number };

const EMPTY: ListedEntries = { shown: [], more: 0, unreadable: 0 };

export function workItemHref(workItemId: string): string {
  return `/chat?area=work&work_item_id=${encodeURIComponent(workItemId)}`;
}

export function exactPlanHref(workItemId: string, changePlanId: string): string {
  return `${workItemHref(workItemId)}&change_plan_id=${encodeURIComponent(changePlanId)}`;
}

// The detail belongs to this session's Work Item. A detail still on screen from the previously
// selected item (the next one is loading) must never name that item's plan.
export function detailBelongsTo(detail: CodingSessionDetailData, workItemId: string): boolean {
  if (detail.workItem && detail.workItem.id !== workItemId) return false;
  return detail.changePlans.every((plan) => plan.work_item_id === workItemId);
}

export function codingWorkAction(
  session: CodingSessionSummary,
  detail: CodingSessionDetailData | null,
  loading: boolean,
): CodingWorkAction {
  const itemHref = workItemHref(session.id);
  const base = { workItemHref: itemHref, planAction: null, questions: EMPTY, blockers: EMPTY };
  const hidden: CodingWorkAction = { ...base, state: "hidden", title: "", message: "", startHint: "" };
  if (session.state === "completed" || (session.state === "cancelled" && !rejectedPlanOnly(session))) return hidden;
  const needsWork = WORK_ACTION_STATES.has(session.state);
  const planNeedsWork = Boolean(session.latestPlanStatus && PLAN_STATUS_GUIDANCE[session.latestPlanStatus]);
  // An ordinary item without any plan yet: Start agent is disabled, so say why and where to go.
  const noPlanYet = !session.latestPlanStatus && session.state === "draft";
  if (!needsWork && !planNeedsWork && !noPlanYet) return hidden;

  if (loading || !detail || !detailBelongsTo(detail, session.id)) {
    return {
      ...base,
      state: "checking",
      title: "Checking what Work needs",
      message: "Loading this session's plan and blockers.",
      startHint: "",
    };
  }

  const plan = latestByVersion(detail.changePlans);
  const blockers = listEntries(recordedBlockers(session, detail));
  const guidance = plan ? PLAN_STATUS_GUIDANCE[plan.status] : undefined;
  if (plan && guidance) {
    // Without recorded questions (a reviewer's clarification request) Work shows no answer field.
    const answerable = plan.status === "needs_clarification" && Array.isArray(plan.open_questions)
      && plan.open_questions.length > 0;
    return {
      ...base,
      state: "plan",
      title: guidance.title(plan.version),
      message: answerable ? ANSWER_GUIDANCE.message(plan.version) : guidance.message,
      startHint: guidance.startHint(plan.version),
      planAction: {
        label: `${answerable ? ANSWER_GUIDANCE.action : guidance.action} (v${plan.version})`,
        href: exactPlanHref(session.id, plan.id),
      },
      questions: listEntries(plan.open_questions),
      blockers,
    };
  }
  if (!plan && (needsWork || session.state === "draft")) {
    return {
      ...base,
      state: "item",
      title: "No Change Plan yet",
      message:
        "Coding needs an approved Change Plan. Open the Work Item and use Generate plan in its Change Plan " +
        "section once repository impact and reviewer setup are available.",
      startHint: "Start agent needs an approved Change Plan; this Work Item has none yet.",
      blockers,
    };
  }
  if (!needsWork || !plan) return hidden;

  if (plan && plan.status === "approved" && session.state === "needs_replan") {
    return {
      ...base,
      state: "plan",
      title: `Plan v${plan.version} is approved but out of date`,
      message:
        "The source task changed after the approval, so a new plan version is needed. Create it from the plan in " +
        "Work with New version; a reviewer then approves it.",
      startHint: `Start agent stays unavailable until a new plan version replaces v${plan.version} and is approved.`,
      planAction: { label: `Open plan v${plan.version}`, href: exactPlanHref(session.id, plan.id) },
      blockers,
    };
  }

  const startHint = "Start agent stays unavailable while this session needs work.";
  const approvedNote =
    plan.status === "approved"
      ? `Plan v${plan.version} is already approved; approving a plan or creating a new version does not clear these blockers.`
      : `These blockers are not resolved on plan v${plan.version}.`;
  return {
    ...base,
    state: "item",
    title: session.state === "needs_human_review" ? "Source evidence needs a human review" : "Coding is blocked",
    message: blockers.shown.length || blockers.unreadable
      ? `${approvedNote} Inspect them on the Work Item or in the task chat.`
      : `${approvedNote} No blocker details are recorded; inspect the Work Item.`,
    startHint,
    blockers,
  };
}

// The session model reads a rejected latest plan as "cancelled". The plan, not the item, ended
// there: a new plan version can follow, unless the Work Item itself is closed.
const CLOSED_ITEM_VALUES = new Set(["cancelled", "canceled", "rejected", "done", "closed", "resolved", "completed"]);

function rejectedPlanOnly(session: CodingSessionSummary): boolean {
  if (session.latestPlanStatus !== "rejected") return false;
  const item = session.workItem;
  return ![item.work_state, item.source_status, item.sync_state].some((value) =>
    CLOSED_ITEM_VALUES.has(String(value || "").trim().toLowerCase()),
  );
}

// Blockers recorded on the source item, its state events and its automation eligibility: the same
// sources the session's blocker count reads, minus the plan's own questions (listed separately).
function recordedBlockers(session: CodingSessionSummary, detail: CodingSessionDetailData): unknown[] {
  const sourceFields = recordValue(session.workItem.source_fields);
  return [
    ...asList(sourceFields?.blockers),
    ...asList(sourceFields?.open_questions),
    ...detail.stateEvents.flatMap((event) => asList(recordValue(event.conflict)?.blockers)),
    ...(session.workItem.automation_eligibility?.blocking_reasons || []),
  ];
}

function asList(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  return value == null || value === "" ? [] : [value];
}

function entryText(entry: unknown): string | null {
  if (typeof entry === "string") return entry.trim() || null;
  const record = recordValue(entry);
  if (!record) return null;
  for (const key of TEXT_KEYS) {
    const value = record[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return null;
}

export function listEntries(entries: readonly unknown[] | null | undefined): ListedEntries {
  const texts: string[] = [];
  let unreadable = 0;
  for (const entry of entries || []) {
    const text = entryText(entry);
    if (text === null) unreadable += 1;
    else if (!texts.includes(text)) texts.push(text);
  }
  return { shown: texts.slice(0, MAX_LISTED), more: Math.max(0, texts.length - MAX_LISTED), unreadable };
}
