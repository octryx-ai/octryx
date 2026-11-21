// Cases and tasks on the phone: Work items, their runs, details, change plans and the proposed workflow.

// Cases (phase A): the Work items labelled for automation ("octryx") and the latest run of each.
export type CaseRun = {
  id: string;
  title: string;
  status: string;
  waitingKind: string | null;
  pauseReason: string | null;
  outcome: string | null;
  updatedAt: string;
  // Who answers the run's questions and approvals: requester, reporter, assignee, or the
  // person who took it over.
  responsible: RunResponsible | null;
};
export type RunResponsible = { userId: string; name: string; source: string };

export function readResponsible(raw: unknown): RunResponsible | null {
  const value = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
  if (!value || typeof value.user_id !== "string" || !value.user_id) return null;
  return {
    userId: value.user_id,
    name: typeof value.display_name === "string" && value.display_name ? value.display_name : "Someone",
    source: typeof value.source === "string" ? value.source : "",
  };
}

const RESPONSIBLE_SOURCES: Record<string, string> = {
  requester: "started it", reporter: "reporter", assignee: "assignee", taken_over: "took it over",
  accepted: "accepted it",
};
export const responsibleText = (responsible: RunResponsible) =>
  `${responsible.name}${RESPONSIBLE_SOURCES[responsible.source] ? ` (${RESPONSIBLE_SOURCES[responsible.source]})` : ""}`;

// Why the platform refused a run action, in words.
const RUN_REFUSALS: Record<string, string> = {
  take_over_not_permitted: "You may not take over this run.",
  run_finished: "The run has already finished.",
  already_responsible: "You are already responsible for this run.",
  workspace_required: "This task has no Workspace. A workflow run needs one: move the task to a Workspace, then start the run.",
  // A run that builds or tests the repository never runs on the server.
  server_build_not_allowed:
    "This workflow builds or tests the repository, which is not allowed on the Octryx server. Run it on your " +
    "Mac (choose your device as the run location) — a sandbox for server runs is coming.",
};
export const runRefusalText = (code: string | null | undefined) =>
  (code && RUN_REFUSALS[code]) || (code ? code.replace(/_/g, " ") : "The action was refused.");

export type Case = {
  id: string;
  key: string;
  title: string;
  state: string;
  url: string;
  reporter: string;
  assignee: string;
  priority: string;
  // Where the task lives on the platform: its Workspace and its source (Jira, ServiceNow, the platform itself).
  projectId: string;
  source: string;
  // Carries the intake's automation label: the platform may run it automatically.
  automatic: boolean;
  run: CaseRun | null;
};

const caseText = (value: unknown) => (typeof value === "string" ? value : "");

export function readCases(itemsRaw: unknown, runsRaw: unknown, { keepOrder = false } = {}): Case[] {
  const items = (itemsRaw as { items?: unknown } | null)?.items;
  const runs = (runsRaw as { runs?: unknown } | null)?.runs;
  const latest = new Map<string, CaseRun>();
  for (const raw of Array.isArray(runs) ? runs : []) {
    const run = (raw ?? {}) as Record<string, unknown>;
    const itemId = caseText((run.work_item as Record<string, unknown> | null)?.id) || caseText(run.work_item_id);
    if (!itemId || !caseText(run.id) || latest.has(itemId)) continue; // runs come newest first
    latest.set(itemId, {
      id: caseText(run.id), title: caseText(run.title), status: caseText(run.status),
      waitingKind: caseText(run.waiting_kind) || null, pauseReason: caseText(run.pause_reason) || null,
      outcome: caseText(run.outcome) || null, updatedAt: caseText(run.updated_at),
      responsible: readResponsible(run.responsible),
    });
  }
  const out: Case[] = [];
  for (const raw of Array.isArray(items) ? items : []) {
    const item = (raw ?? {}) as Record<string, unknown>;
    if (!caseText(item.id)) continue;
    out.push({
      id: caseText(item.id), key: caseText(item.source_key), title: caseText(item.title) || caseText(item.source_key),
      state: caseText(item.work_state) || caseText(item.source_status), url: caseText(item.source_url),
      reporter: caseText(item.reporter_display) || caseText(item.reporter),
      assignee: caseText(item.assignee_display) || caseText(item.assignee), priority: caseText(item.priority),
      projectId: caseText(item.project_id), source: caseText(item.source_type),
      automatic: Array.isArray(item.labels) && item.labels.some((label) => String(label).toLowerCase() === "octryx"),
      run: latest.get(caseText(item.id)) ?? null,
    });
  }
  if (keepOrder) return out; // a page of the task list: the platform's order (newest change first)
  const rank = (entry: Case) =>
    entry.run && (entry.run.status === "waiting" || entry.run.status === "paused") ? 0 : entry.run?.status === "running" ? 1 : 2;
  return out.sort((a, b) => rank(a) - rank(b) || (b.run?.updatedAt ?? "").localeCompare(a.run?.updatedAt ?? ""));
}

// The open task list (the app must show which tasks are open and where they
// are kept): the Work items that are not finished, with how many sit in each state.
const STATE_ORDER = ["intake", "clarification", "planning", "ready_for_development", "development", "in_progress",
  "review", "changes_requested", "blocked"];
const STATE_LABELS: Record<string, string> = {
  intake: "Intake", clarification: "Clarification", planning: "Planning", ready_for_development: "Ready",
  development: "In development", in_progress: "In progress", review: "Review", changes_requested: "Changes requested",
  blocked: "Blocked",
};

export function stateLabel(state: string): string {
  if (STATE_LABELS[state]) return STATE_LABELS[state];
  const text = state.replace(/_/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : "Open";
}

export type TaskCounts = { total: number; states: { state: string; label: string; count: number }[] };

export function readTaskCounts(raw: unknown): TaskCounts {
  const page = (raw ?? {}) as { total?: unknown; state_counts?: unknown };
  const counts = page.state_counts && typeof page.state_counts === "object" ? page.state_counts as Record<string, unknown> : {};
  const states = Object.entries(counts)
    .filter(([, count]) => typeof count === "number" && count > 0)
    .map(([state, count]) => ({ state, label: stateLabel(state), count: count as number }))
    .sort((a, b) => {
      const rank = (state: string) => (STATE_ORDER.includes(state) ? STATE_ORDER.indexOf(state) : STATE_ORDER.length);
      return rank(a.state) - rank(b.state) || a.state.localeCompare(b.state);
    });
  const total = states.reduce((sum, item) => sum + item.count, 0);
  return { total: total || (typeof page.total === "number" ? page.total : 0), states };
}

export function nextOffset(raw: unknown): number | null {
  const value = (raw as { next_offset?: unknown } | null)?.next_offset;
  return typeof value === "number" ? value : null;
}

const SOURCES: Record<string, string> = { jira: "Jira", servicenow: "ServiceNow", platform: "Platform" };
export const sourceLabel = (source: string) => SOURCES[source] ?? (source ? source[0].toUpperCase() + source.slice(1) : "");

// A task opened on the phone: what the ticket says and what the platform knows about it.
export type TaskComment = { key: string; author: string; created: string; body: string };
export type TaskDetail = {
  description: string;
  issueType: string;
  labels: string[];
  comments: TaskComment[];
  commentsTotal: number;
};

const MAX_DESCRIPTION = 6000;

export function readTaskDetail(raw: unknown): TaskDetail | null {
  const item = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : null;
  if (!item || !caseText(item.id)) return null;
  const comments = (Array.isArray(item.comments) ? item.comments : [])
    .map((entry, index) => {
      const comment = (entry ?? {}) as Record<string, unknown>;
      return {
        key: caseText(comment.id) || String(index),
        author: caseText(comment.author_display) || caseText(comment.author),
        created: caseText(comment.created),
        body: caseText(comment.body).trim(),
      };
    })
    .filter((comment) => comment.body);
  return {
    description: caseText(item.description).trim().slice(0, MAX_DESCRIPTION),
    issueType: caseText(item.issue_type),
    labels: (Array.isArray(item.labels) ? item.labels : []).map(String).filter(Boolean),
    comments: comments.slice(-3).reverse(),
    commentsTotal: typeof item.comments_total === "number" ? item.comments_total : comments.length,
  };
}

// The task's change plan: the newest one that is not superseded (the platform lists the newest version first).
export type TaskPlan = {
  status: string;
  version: number;
  title: string;
  understood: string;
  openQuestions: string[];
  acceptance: number;
};

export function readTaskPlan(raw: unknown): TaskPlan | null {
  const items = (raw as { items?: unknown } | null)?.items;
  const plan = (Array.isArray(items) ? items : [])
    .map((entry) => (entry ?? {}) as Record<string, unknown>)
    .find((entry) => caseText(entry.status) !== "superseded");
  if (!plan) return null;
  const questions = (Array.isArray(plan.open_questions) ? plan.open_questions : [])
    .map((question) => (typeof question === "string" ? question : caseText((question as Record<string, unknown>)?.question)))
    .filter(Boolean);
  return {
    status: caseText(plan.status),
    version: typeof plan.version === "number" ? plan.version : 1,
    title: caseText(plan.title),
    understood: caseText(plan.understood_request).trim().slice(0, 1200),
    openQuestions: questions.slice(0, 5),
    acceptance: Array.isArray(plan.acceptance_criteria) ? plan.acceptance_criteria.length : 0,
  };
}

const PLAN_STATES: Record<string, string> = {
  draft: "Draft", needs_clarification: "Needs clarification", ready_for_review: "Waiting for approval",
  approved: "Approved", rejected: "Rejected",
};
export const planStatusLabel = (status: string) => PLAN_STATES[status] ?? stateLabel(status);

// Which workflow a task's run starts with, proposed (a ticket is analysed and routed by kind): a bug
// gets the bug fix, an incident the incident analysis, a ticket still in intake or clarification the triage, a ready
// one Story / epic delivery (``epic-delivery``). The person can always pick another; a key the Workspace does not offer is never proposed.
export type StartableFlow = { key: string; title: string; kind: string };

export function readStartable(raw: unknown): StartableFlow[] {
  const flows = (raw as { workflows?: unknown } | null)?.workflows;
  return (Array.isArray(flows) ? flows : [])
    .map((entry) => (entry ?? {}) as Record<string, unknown>)
    .filter((entry) => typeof entry.key === "string" && entry.key)
    .map((entry) => ({ key: String(entry.key), title: caseText(entry.title) || String(entry.key), kind: caseText(entry.kind) }));
}

export function suggestWorkflow(flows: StartableFlow[], state: string, issueType: string, source = ""): string {
  const offered = new Set(flows.map((flow) => flow.key));
  const type = issueType.toLowerCase();
  const wanted = type.includes("incident") || (source === "servicenow" && type === "incident")
    ? ["incident-analysis"]
    : type.includes("bug") || type.includes("defect")
      ? ["bug-fix-reproduction"]
      : state === "intake" || state === "clarification"
        ? ["jira-intake-triage"]
        : ["epic-delivery"];
  return [...wanted, "jira-intake-triage"].find((key) => offered.has(key)) ?? flows[0]?.key ?? "";
}
