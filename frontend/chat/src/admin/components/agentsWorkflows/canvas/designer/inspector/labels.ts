// Plain words for the designer's side panel (owner: easy to understand, plain words, no raw values). Every closed
// value the backend knows gets a sentence-case name; an unknown value falls back to readable words, never a code.

const words = (value: string) => {
  const text = value.replace(/^role:/, "").replace(/[._-]+/g, " ").trim();
  return text ? text[0].toUpperCase() + text.slice(1) : value;
};
const from = (map: Record<string, string>) => (value: string) => map[value] ?? words(value);

export const KIND_NAMES: Record<string, string> = {
  start: "Start", phase: "Agent step", gate: "Check", decision: "Condition", outcome: "End",
  platform_action: "Platform action", user_conversation: "Question to a person", user_confirmation: "Confirmation",
  watch: "Wait for an event", approval: "Approval", sub_workflow: "Sub-workflow", review: "Independent review",
  pause: "Pause", parallel_work: "Parallel work",
};
export const kindName = from(KIND_NAMES);

export const CAPABILITY_NAMES: Record<string, string> = {
  read_only: "Read only — looks, changes nothing",
  change: "Change — may edit files",
  deliver: "Deliver — may edit, push and open a pull request",
};
export const capabilityName = from(CAPABILITY_NAMES);
export const CAPABILITY_ORDER = ["read_only", "change", "deliver"] as const;

export const EXIT_NAMES: Record<string, string> = {
  passed: "Passed", failed: "Failed", confirmed: "Confirmed", changed: "Asked for changes", stopped: "Stopped",
  approved: "Approved", rejected: "Rejected", succeeded: "Succeeded", accepted: "Accepted",
  not_testable_yet: "Not testable yet", delivered: "Delivered", done: "Done", blocked: "Blocked",
  done_with_exception: "Done with an exception",
  "pr.approved": "Pull request approved", "pr.merged": "Pull request merged", "pr.declined": "Pull request declined",
  "ci.succeeded": "CI succeeded", "ci.failed": "CI failed", "jira.status": "Jira status changed",
  "approval.decided": "Approval decided", yes: "Yes", no: "Otherwise", otherwise: "Otherwise",
};
export const exitName = from(EXIT_NAMES);
export const conditionName = exitName;
export const outcomeName = exitName;

export const SUBJECT_NAMES: Record<string, string> = {
  test_contract: "The test contract (the plan)", ticket_draft: "The ticket draft", reproduction: "The reproduction",
  retry_choice: "How to retry", advance: "Whether to go on", questions: "The open questions",
  documentation: "The documentation", functional_acceptance: "The functional acceptance",
  publication: "The publication", followup: "The follow-up", exception: "The exception",
};
export const subjectName = from(SUBJECT_NAMES);

export const DECIDER_NAMES: Record<string, string> = {
  requester: "The person who started the run", item_owner: "The ticket's assignee",
  handoff_owner: "The owner of the hand-over", spec_origin: "The person who confirmed the specification",
};
export const deciderName = (value: string) =>
  DECIDER_NAMES[value] ?? (value.startsWith("role:") ? `Anyone with the role ${words(value)}` : words(value));

export const STEP_MODE_NAMES: Record<string, string> = {
  strict: "Must happen — the step cannot finish without it",
  guided: "Should happen — one reminder, then it goes on",
};
export const stepModeName = from(STEP_MODE_NAMES);

export const OPERATOR_NAMES: Record<string, string> = {
  is: "is", is_not: "is not", contains: "contains", greater_than: "is greater than", less_than: "is less than",
};
export const operatorName = from(OPERATOR_NAMES);
/** Which comparisons a field of each kind offers (agreed with octryx-work, D2b2). */
export const OPERATORS_BY_KIND: Record<string, string[]> = {
  enum: ["is", "is_not"], text: ["is", "is_not", "contains"], list: ["contains"],
  number: ["is", "is_not", "greater_than", "less_than"],
};

/** Which kind of work a tool does, to group long tool lists. */
export type ToolGroup = "read" | "change" | "run" | "helper";
export const TOOL_GROUP_NAMES: Record<ToolGroup, string> = {
  read: "Read and search", change: "Change files", run: "Run tests and commands", helper: "Helpers",
};
export function toolGroup(tool: string): ToolGroup {
  if (/^(write|edit|multi_edit|create|delete|move|rename|apply)_/.test(tool)) return "change";
  if (/^run_/.test(tool) || tool === "bash") return "run";
  if (/^(todo_|submit_|spawn_)/.test(tool) || tool === "get_context_from_subthreads") return "helper";
  return "read";
}

export const PARAM_NAMES: Record<string, string> = {
  tools: "Which tools", regression: "Which other tests must still pass", minimum: "At least how many",
  families: "Which kinds of evidence",
};
export const paramName = from(PARAM_NAMES);

/** A tool in words ("write_workspace_file" → "Write workspace file"); the catalog has no names for tools yet. */
export const toolName = (value: string) => words(value);
