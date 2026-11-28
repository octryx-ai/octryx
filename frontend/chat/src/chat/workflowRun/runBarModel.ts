import type { RunRuntimeTarget } from "./runtimeTargetModel";
import type { RunAction, WorkflowRun } from "./workflowRunTypes";

const ACRONYMS = new Set(["tdd", "ci", "cd", "pr", "aws", "api", "ui", "ux", "qa", "sla", "itsm"]);

export function runWorkflowName(run: Pick<WorkflowRun, "workflow_key"> & { workflow_title?: string | null }): string {
  const title = String(run.workflow_title ?? "").trim();
  if (title) return title;
  const words = String(run.workflow_key || "").split(/[-_.\s]+/).filter(Boolean)
    .map((word) => (ACRONYMS.has(word.toLowerCase()) ? word.toUpperCase() : word.toLowerCase()));
  if (!words.length) return "Workflow run";
  words[0] = words[0] === words[0].toUpperCase() ? words[0] : words[0][0].toUpperCase() + words[0].slice(1);
  return words.join(" ");
}

export function runPhaseShort(run: Pick<WorkflowRun, "current_node" | "phase_position" | "status">): string {
  const { index, total } = run.phase_position ?? { index: null, total: 0 };
  if (run.status === "completed" && total) return `Phase ${total}/${total}`;
  const onStep = run.current_node?.kind === "phase" || run.current_node?.kind === "parallel_work";
  if (onStep && index && total) return `Phase ${index}/${total}`;
  return run.current_node?.title ?? (index && total ? `Phase ${index}/${total}` : "");
}

export function runPlaceText(target: RunRuntimeTarget | null | undefined): string {
  if (!target?.label) return "";
  const label = /^the server$/i.test(target.label.trim()) ? "the server" : target.label;
  return `on ${label}${target.kind === "device" && target.online === false ? " · offline" : ""}`;
}
export function runActsAtOnce(action: RunAction): boolean {
  return !action.input;
}

const OPEN_KEY = "octryx.runbar.open.";

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
