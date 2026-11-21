// The run bar: workflow name, phase, place, primary-action mode, open state and the shared run thread titles.
import type { RunRuntimeTarget } from "./runtimeTargetModel";
import type { RunAction, WorkflowRun } from "./workflowRunTypes";

// ---- The run bar (product inventory): one quiet line "Workflow · Phase n/m · State · Where" --------------

const ACRONYMS = new Set(["tdd", "ci", "cd", "pr", "aws", "api", "ui", "ux", "qa", "sla", "itsm"]);

/** The workflow's name for people: its definition's current name (``workflow_title``), else derived from the key:
 * "pr-review-bot" → "PR review bot" (outsider walkthrough: "Epic delivery" after the rename). */
export function runWorkflowName(run: Pick<WorkflowRun, "workflow_key"> & { workflow_title?: string | null }): string {
  const title = String(run.workflow_title ?? "").trim();
  if (title) return title;
  const words = String(run.workflow_key || "").split(/[-_.\s]+/).filter(Boolean)
    .map((word) => (ACRONYMS.has(word.toLowerCase()) ? word.toUpperCase() : word.toLowerCase()));
  if (!words.length) return "Workflow run";
  words[0] = words[0] === words[0].toUpperCase() ? words[0] : words[0][0].toUpperCase() + words[0].slice(1);
  return words.join(" ");
}

/** "Phase 2/3" while the run stands on a phase; the node's title outside the phases ("Prepare folder"); else "". */
export function runPhaseShort(run: Pick<WorkflowRun, "current_node" | "phase_position" | "status">): string {
  const { index, total } = run.phase_position ?? { index: null, total: 0 };
  if (run.status === "completed" && total) return `Phase ${total}/${total}`;
  const onStep = run.current_node?.kind === "phase" || run.current_node?.kind === "parallel_work";
  if (onStep && index && total) return `Phase ${index}/${total}`;
  return run.current_node?.title ?? (index && total ? `Phase ${index}/${total}` : "");
}

/** Where the run works, as the end of the bar: "on the server", "on Studio Mac · offline". */
export function runPlaceText(target: RunRuntimeTarget | null | undefined): string {
  if (!target?.label) return "";
  const label = /^the server$/i.test(target.label.trim()) ? "the server" : target.label;
  return `on ${label}${target.kind === "device" && target.online === false ? " · offline" : ""}`;
}
/** Whether the bar's primary button acts at once; an action that asks for a value opens the details instead. */
export function runActsAtOnce(action: RunAction): boolean {
  return !action.input;
}

const OPEN_KEY = "octryx.runbar.open.";

/** Whether the bar's details are open for this run (per browser tab; collapsed by default). */
export function runBarOpen(store: Pick<Storage, "getItem"> | null, runId: string): boolean {
  try {
    return store?.getItem(OPEN_KEY + runId) === "1";
  } catch {
    return false;
  }
}

export function rememberRunBarOpen(store: Pick<Storage, "setItem" | "removeItem"> | null, runId: string, open: boolean) {
  try {
    if (open) store?.setItem(OPEN_KEY + runId, "1");
    else store?.removeItem(OPEN_KEY + runId);
  } catch {
    // Blocked storage: the bar simply starts collapsed next time.
  }
}

// The open thread's run title for the chat header: the banner loads the run, the header shows its title. One
// title per session id, kept in memory only.
type Listener = () => void;
const titles = new Map<string, string>();
const listeners = new Set<Listener>();

export function publishRunThreadTitle(sessionId: string | null | undefined, title: string | null) {
  if (!sessionId) return;
  if (title ? titles.get(sessionId) === title : !titles.has(sessionId)) return;
  if (title) titles.set(sessionId, title);
  else titles.delete(sessionId);
  listeners.forEach((listener) => listener());
}

export function runThreadTitleOf(sessionId: string | null | undefined): string | null {
  return sessionId ? titles.get(sessionId) ?? null : null;
}

export function subscribeRunThreadTitles(listener: Listener): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}
