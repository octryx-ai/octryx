// Starting a phased workflow from the chat (contract of `phased_start.py`).
// A phased workflow selected in the chat holds the turn with one start card: the Work item it works on, where the
// run executes and its steps. "Other workflow…" swaps the pending proposal's workflow for one from the composer's
// catalog. Pure: no React, so the unit harness can load it.

import type { WorkflowProposalView } from "../../chatDecisionTypes";
import { workItemHref } from "../agents/agentBoardModel";
import { record, text, textOrNull } from "./workflowStartValues";

export type RunOnChoice = { key: string; label: string; help: string | null; offline: boolean };

export type WorkflowStartItem = {
  mode: "new" | "existing";
  typeLabel: string;
  title: string;
  description: string;
  // A long description starts folded so the card's actions stay in view.
  longDescription: boolean;
  key: string | null;
  href: string | null;
  // The existing item's id (its run limits can be set before the start); null for a new item.
  id: string | null;
};

// What a start already made. `started` fills step by step (the Jira issue, the Work item, the run), so a refused
// start can show what exists before it says why the run did not start.
export type WorkflowStartProgress = {
  // The Work item a refused start already made (a "Start again" can set its budget first).
  itemId: string | null;
  itemKey: string | null;
  itemHref: string | null;
  jiraKey: string | null;
  jiraProblem: string | null;
};

export type WorkflowStartOutcome =
  | { kind: "none" }
  | ({ kind: "started"; href: string; runId: string | null } & WorkflowStartProgress)
  // A typed refusal carries its state and reason (`needs_configuration` / `workspace_required`): it says what to
  // configure, and "Start again" would only be refused again.
  | ({ kind: "error"; reason: string; state: string | null; code: string | null } & WorkflowStartProgress);

export type RepositoryChoice = { id: string; name: string };

// The repository a run works in (`start.repository`); null for a workflow that works in none.
export type WorkflowStartRepository = {
  // The chosen repository's name, or null while the person still has to choose one.
  name: string | null;
  id: string | null;
  // Where the choice comes from, in words ("named in your request").
  sourceText: string | null;
  options: RepositoryChoice[];
};

export type WorkflowStartView = {
  workflowKey: string;
  projectId: string | null;
  workflowTitle: string;
  summary: string;
  item: WorkflowStartItem;
  jiraProject: string | null;
  // The Jira issue the start also creates ("+ Jira MM: Epic 'Hello Kitchen'"); null when none.
  jiraLabel: string | null;
  notes: string[];
  runOn: { options: RunOnChoice[]; selected: string };
  steps: string[];
  repository: WorkflowStartRepository | null;
  outcome: WorkflowStartOutcome;
};

/** Why "Start" cannot be pressed while the repository is missing. */
export const CHOOSE_REPOSITORY_HINT = "Choose the repository the run works in";
const NO_REPOSITORY_HINT = "This Workspace has no repository a run can use yet.";

const REPOSITORY_SOURCES: Record<string, string> = {
  request: "named in your request",
  only_coding_repository: "the Workspace's only coding repository",
  work_item: "from the Work item",
  chosen: "chosen by you",
};

const LONG_DESCRIPTION_CHARS = 280;
const LONG_DESCRIPTION_LINES = 4;
const OFFLINE_HELP = "This device is offline; the run waits for it.";

// Only an address inside the product is followed; anything else is not a link.
function localHref(value: unknown): string | null {
  const href = text(value);
  return href.startsWith("/") && !href.startsWith("//") ? href : null;
}

function readItem(raw: unknown, projectId: string | null): WorkflowStartItem {
  const item = record(raw) ?? {};
  const description = text(item.description);
  const id = text(item.id);
  const existing = item.mode === "existing";
  return {
    mode: existing ? "existing" : "new",
    typeLabel: text(item.type_label) || "Work item",
    title: text(item.title),
    description,
    longDescription:
      description.length > LONG_DESCRIPTION_CHARS || description.split("\n").length > LONG_DESCRIPTION_LINES,
    key: textOrNull(item.key),
    href: existing && id && projectId ? `/chat${workItemHref(projectId, id)}` : null,
    id: existing && id ? id : null,
  };
}

function readRunOn(raw: unknown): WorkflowStartView["runOn"] {
  const runOn = record(raw) ?? {};
  const options = (Array.isArray(runOn.options) ? runOn.options : []).flatMap((entry): RunOnChoice[] => {
    const option = record(entry);
    const key = text(option?.key);
    const label = text(option?.label);
    if (!option || !key || !label) return [];
    const offline = option.online === false;
    return [{ key, label: offline ? `${label} · offline` : label, help: textOrNull(option.help) ?? (offline ? OFFLINE_HELP : null), offline }];
  });
  const has = (key: string) => options.some((option) => option.key === key);
  // The person's earlier choice on this card ("chosen"), else the server's default, else the first option.
  const selected = [text(runOn.chosen), text(runOn.default)].find((key) => key && has(key)) ?? options[0]?.key ?? "";
  return { options, selected };
}

function readRepository(raw: unknown): WorkflowStartRepository | null {
  const repository = record(raw);
  if (!repository) return null;
  const options = (Array.isArray(repository.options) ? repository.options : []).flatMap((entry): RepositoryChoice[] => {
    const option = record(entry);
    const id = text(option?.id);
    const name = text(option?.name) || text(option?.ref);
    return id && name ? [{ id, name }] : [];
  });
  const ref = text(repository.ref);
  return {
    name: ref ? text(repository.name) || ref : null,
    id: ref ? textOrNull(repository.id) : null,
    sourceText: ref ? REPOSITORY_SOURCES[text(repository.source)] ?? null : null,
    options,
  };
}

function readProgress(started: Record<string, unknown>, projectId: string | null): WorkflowStartProgress {
  // The Jira issue is optional: the run starts with the platform item when it could not be created.
  const jira = record(started.jira);
  const itemId = text(started.work_item_id);
  const itemKey = textOrNull(started.work_item_key);
  const jiraKey = textOrNull(jira?.key);
  return {
    itemId: itemId || null,
    itemKey,
    itemHref: itemId && projectId ? `/chat${workItemHref(projectId, itemId)}` : null,
    // A platform item created from the Jira issue carries the issue's key: show it once, not twice.
    jiraKey: jiraKey && jiraKey !== itemKey ? jiraKey : null,
    jiraProblem: jira && !text(jira.key) ? text(jira.error) || "no reason given" : null,
  };
}

function readOutcome(raw: unknown, projectId: string | null): WorkflowStartOutcome {
  const started = record(raw);
  if (!started) return { kind: "none" };
  const progress = readProgress(started, projectId);
  const error = text(started.error);
  if (error)
    return { kind: "error", reason: error, state: textOrNull(started.state), code: textOrNull(started.reason), ...progress };
  const href = localHref(started.href);
  if (!href) return { kind: "none" };
  return { kind: "started", href, runId: textOrNull(started.run_id), ...progress };
}

/** Why "Start" cannot be pressed in a chat without a Workspace (the server refuses it with `workspace_required`). */
export const CHOOSE_WORKSPACE_HINT = "A workflow run needs a Workspace: choose a Workspace for this chat first";

/** Whether the refused start needs configuration first: pressing "Start again" would be refused the same way. */
export function needsConfiguration(outcome: WorkflowStartOutcome): boolean {
  return outcome.kind === "error" && outcome.state === "needs_configuration";
}

/** Why "Start" cannot be pressed now: no Workspace, then the repository; null when it can. */
export function startBlockedReason(view: Pick<WorkflowStartView, "projectId" | "repository">, chosenId: string): string | null {
  if (!view.projectId) return CHOOSE_WORKSPACE_HINT;
  return repositoryBlockedReason(view.repository, chosenId);
}

/** Why "Start" waits for the repository; null when it is known, chosen on the card, or not needed. */
export function repositoryBlockedReason(repository: WorkflowStartRepository | null, chosenId: string): string | null {
  if (!repository || repository.name || chosenId) return null;
  return repository.options.length ? CHOOSE_REPOSITORY_HINT : NO_REPOSITORY_HINT;
}

/** The button that sends Start again after a refused start (the server's reason ends with "Press Start again"). */
export function startButtonLabel(outcome: WorkflowStartOutcome): string {
  return outcome.kind === "error" ? "Start again" : "Start";
}

/** The start card of a phased proposal; null for any other proposal or a draft the card cannot show. */
export function workflowStartView(proposal: WorkflowProposalView | null | undefined): WorkflowStartView | null {
  if (!proposal || proposal.phased !== true) return null;
  const start = record(proposal.start);
  if (!start) return null;
  const workflowTitle = text(start.workflow_title) || proposal.workflowTitle || text(start.workflow_key);
  const projectId = textOrNull(start.project_id);
  const item = readItem(start.work_item, projectId);
  return {
    workflowKey: text(start.workflow_key) || proposal.workflowKey || "",
    projectId,
    workflowTitle,
    summary: text(start.summary) || `Start ${workflowTitle}`,
    item,
    jiraProject: textOrNull(start.jira_project),
    jiraLabel: textOrNull(record(start.jira)?.label),
    notes: (Array.isArray(start.notes) ? start.notes : []).map(text).filter(Boolean),
    runOn: readRunOn(start.run_on),
    steps: (Array.isArray(start.steps) ? start.steps : []).map((step) => text(record(step)?.title)).filter(Boolean),
    repository: readRepository(start.repository),
    outcome: readOutcome(proposal.started, projectId),
  };
}

/** The help sentence below "Run on" for the chosen option. */
export function runOnHelp(view: WorkflowStartView["runOn"], key: string): string | null {
  return view.options.find((option) => option.key === key)?.help ?? null;
}

/** The quiet note after a start whose Jira issue was refused. */
export function jiraProblemText(reason: string): string {
  return `Jira issue could not be created: ${reason} – the run started with a platform item.`;
}

/** The link text after the start: "Open the run" plus the Work item key when there is one. */
export function startedLinkLabel(outcome: Extract<WorkflowStartOutcome, { kind: "started" }>): string {
  return outcome.itemKey ? `Open the run · ${outcome.itemKey}` : "Open the run";
}
