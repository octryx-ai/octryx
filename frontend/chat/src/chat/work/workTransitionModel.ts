import type { WorkItem } from "./workItemTypes";
import type { WorkStateEvent, WorkTransitionPreview, WorkWorkflowDefinition } from "./workSyncWorkflowTypes";
import { workStateKey } from "./workBoardColumns";
import { SYNC_MODE_EXECUTE, syncModeOf } from "./syncNames";

// Applying a workflow transition from the Work Item detail. Pure: no requests, no React.
//
// The author picks the workflow (when several apply) and the target state, previews it (the server's dry run),
// and applies only that previewed transition in a second explicit step. The preview lists exactly what the apply
// writes to Jira (`jira_sync_preview.effects`, `will_mutate_jira`) and binds the apply to them (`effects_hash`).

/** The workflows that can move this item: active, and global or of the item's Workspace. */
export function workflowsForItem(item: WorkItem, workflows: WorkWorkflowDefinition[]): WorkWorkflowDefinition[] {
  return workflows.filter(
    (workflow) => workflow.is_active && (!workflow.project_id || workflow.project_id === item.project_id),
  );
}

/** The one preselected: the Workspace's default, else its first, else the global default, else the first. */
export function preselectedWorkflow(item: WorkItem, candidates: WorkWorkflowDefinition[]): WorkWorkflowDefinition | null {
  const own = candidates.filter((workflow) => workflow.project_id && workflow.project_id === item.project_id);
  const global = candidates.filter((workflow) => !workflow.project_id);
  return own.find((workflow) => workflow.is_default) ?? own[0] ?? global.find((workflow) => workflow.is_default) ?? global[0] ?? null;
}

/** Target states: the workflow's states except the item's current one. */
export function targetStates(item: WorkItem, workflow: WorkWorkflowDefinition | null): { key: string; label: string }[] {
  if (!workflow) return [];
  const current = workStateKey(item.work_state);
  return (workflow.states || []).filter((state) => workStateKey(state.key) !== current);
}

export type JiraEffect = { kind: string; text: string };

function valueText(value: unknown): string {
  if (Array.isArray(value)) return value.map((entry) => String(entry)).join(", ");
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}

function effectText(kind: string, value: unknown): string {
  if (kind === "status") return `Status → ${valueText(value)}`;
  if (kind === "comment") return `Comment: ${valueText(value)}`;
  if (kind === "labels") return `Labels: ${valueText(value)}`;
  return `${kind}: ${valueText(value)}`;
}

export type TransitionPlan = {
  /** The apply writes to Jira. */
  writesToJira: boolean;
  effects: JiraEffect[];
  /** Why nothing is written, when it is not. */
  localReason: string | null;
  /** Jira changed after the last sync: the apply would be refused. */
  conflict: string | null;
  /**
   * r8: the server's preview says the apply would be refused before anything is written (`blocked_reason`, or Jira
   * not offering the mapped transition: `transition_available: false`). Then nothing is claimed about writing, and
   * the apply is not offered.
   */
  blocked: string | null;
  /** What Jira offers from the issue's current status ("Done → Done"), when the server read it. */
  offers: string[];
};

export function transitionPlan(
  item: WorkItem,
  workflow: WorkWorkflowDefinition | null,
  preview: WorkTransitionPreview,
): TransitionPlan {
  const sync = preview.jira_sync_preview;
  const execute = syncModeOf(workflow?.sync_policy) === SYNC_MODE_EXECUTE;
  const jira = item.source_type === "jira";
  const effects: JiraEffect[] = sync.effects.map((effect) => {
    const kind = String(effect?.kind || "");
    return { kind, text: kind === "status" ? statusEffectText(effect, sync) : effectText(kind, effect?.value) };
  });
  const writes = sync.will_mutate_jira === true;
  let localReason: string | null = null;
  if (!writes) {
    localReason = !jira
      ? "This item is not from Jira, so only Octryx changes."
      : !execute
        ? "This workflow syncs to Jira in dry-run mode only, so nothing is written to Jira."
        : !sync.sync_back
          ? "The target state has no Jira sync-back, so nothing is written to Jira."
          : "The target state maps to nothing to write, so nothing is written to Jira.";
  }
  const conflict = preview.conflict?.has_conflict
    ? `Jira changed after this item was last synced${preview.conflict.reason ? ` (${preview.conflict.reason})` : ""}: run the intake sync first, then preview again.`
    : null;
  const offers = offeredTransitions(sync);
  const blocked = blockedText(sync);
  if (blocked) return { writesToJira: false, effects: [], localReason: null, conflict, blocked, offers };
  return { writesToJira: writes, effects: writes ? effects : [], localReason, conflict, blocked: null, offers };
}

const BLOCKED_TEXT: Record<string, string> = {
  scope_not_allowed:
    "This item's Jira project is outside the Workspace's allowed Jira projects, so applying would be refused and nothing would be written.",
};

/** Why the apply would be refused, from the server's preview (C-9 `blocked_reason`, L-a `transition_available`). */
export function blockedText(sync: WorkTransitionPreview["jira_sync_preview"] | null | undefined): string | null {
  const reason = typeof sync?.blocked_reason === "string" ? sync.blocked_reason.trim() : "";
  if (reason) return BLOCKED_TEXT[reason] ?? `Applying would be refused (${reason}), so nothing would be written.`;
  if (sync?.transition_available === false) {
    const mapped = (typeof sync.transition === "string" && sync.transition) || (typeof sync.target_status === "string" && sync.target_status) || "";
    return `Jira does not offer the mapped transition${mapped ? ` “${mapped}”` : ""} from the issue's current status, so applying would be refused before anything is written.`;
  }
  return null;
}

/** The server's `offered_transitions` (`[{name, to}]`) as "Name → Status" lines. */
export function offeredTransitions(sync: WorkTransitionPreview["jira_sync_preview"] | null | undefined): string[] {
  const entries = Array.isArray(sync?.offered_transitions) ? sync.offered_transitions : [];
  return entries.flatMap((entry) => {
    const name = typeof entry?.name === "string" ? entry.name.trim() : "";
    const to = typeof entry?.to === "string" ? entry.to.trim() : "";
    if (!name && !to) return [];
    if (!name) return [`→ ${to}`];
    return [to && to !== name ? `${name} → ${to}` : name];
  });
}

const INACTIVE_TEXT =
  "This workflow is deactivated, so it cannot move items. Choose an active workflow, or ask a Workspace admin to activate it.";
const SCOPE_TEXT =
  "This item's Jira project is outside the Workspace's allowed Jira projects, so nothing was written to Jira.";
const STALE_TEXT =
  "The workflow or what it writes to Jira changed after the preview, so nothing was applied. Preview again to see what would be written now.";

/** A Python list of string literals as the server prints it (`['a', "Won't do"]`, with \\ escapes); null otherwise. */
export function parseStringList(raw: string): string[] | null {
  const text = raw.trim();
  if (!text.startsWith("[") || !text.endsWith("]")) return null;
  const end = text.length - 1;
  const values: string[] = [];
  let index = 1;
  const skipSpace = () => {
    while (index < end && /\s/.test(text[index])) index += 1;
  };
  skipSpace();
  while (index < end) {
    const quote = text[index];
    if (quote !== "'" && quote !== '"') return null;
    index += 1;
    let value = "";
    while (index < end && text[index] !== quote) {
      if (text[index] === "\\" && index + 1 < end) {
        value += text[index + 1];
        index += 2;
      } else {
        value += text[index];
        index += 1;
      }
    }
    if (index >= end) return null;
    index += 1;
    values.push(value.trim());
    skipSpace();
    if (index === end) break;
    if (text[index] !== ",") return null;
    index += 1;
    skipSpace();
  }
  return values.filter(Boolean);
}

export type TransitionRefusal = { text: string; offers: string[] | null; stale: boolean };

/** A refused preview or apply: the server's text, Jira's offered transitions when the message carries them, and
 *  whether the preview went stale (409 `preview_stale` C-7), which always needs a new preview. */
export function transitionRefusal(error: unknown): TransitionRefusal {
  const record = error && typeof error === "object" ? (error as { message?: unknown; code?: unknown }) : null;
  if (record?.code === "preview_stale") return { text: STALE_TEXT, offers: null, stale: true };
  // Refusals with dedicated backend error codes.
  if (record?.code === "workflow_inactive") return { text: INACTIVE_TEXT, offers: null, stale: true };
  if (record?.code === "scope_not_allowed") return { text: SCOPE_TEXT, offers: null, stale: true };
  const text = typeof record?.message === "string" && record.message ? record.message : "The transition was not applied.";
  const match = /Jira offers: (.*)$/.exec(text);
  if (!match) return { text, offers: null, stale: false };
  const list = match[1].trim();
  // An unreadable list is not guessed at: the server's text still says what Jira offers.
  const offers = list === "none" ? [] : parseStringList(list);
  // L-f: once read, the offers are shown once, as the list below the sentence, not again inside it.
  return { text: offers ? text.slice(0, match.index).trim() : text, offers, stale: false };
}

/** The status line of what an apply writes: the target status when known, a transition never posing as a status. */
export function statusEffectText(
  effect: { value?: unknown; target_status?: unknown; transition?: unknown } | null | undefined,
  sync: WorkTransitionPreview["jira_sync_preview"],
): string {
  const named = (value: unknown) => (typeof value === "string" && value.trim() ? value.trim() : null);
  const target = named(effect?.target_status) ?? named(sync?.target_status);
  const transition = named(effect?.transition) ?? named(sync?.transition);
  if (target) return `Status → ${target}${transition ? ` (via the transition “${transition}”)` : ""}`;
  const value = named(effect?.value);
  if (transition && (!value || value === transition)) {
    return `Transition “${transition}” (Jira decides the resulting status)`;
  }
  return `Status → ${value ?? ""}`;
}

/** What binds an apply to its preview (`jira_sync_preview.effects_hash`, `workflow_updated_at`), sent back with the
 * apply. */
export function previewBinding(preview: WorkTransitionPreview | null): { effects_hash?: string; workflow_updated_at?: string } {
  if (!preview) return {};
  const sync = preview.jira_sync_preview || {};
  const pick = (key: "effects_hash" | "workflow_updated_at") => {
    const value = sync[key];
    return typeof value === "string" && value ? value : null;
  };
  const hash = pick("effects_hash");
  const updated = pick("workflow_updated_at");
  return { ...(hash ? { effects_hash: hash } : {}), ...(updated ? { workflow_updated_at: updated } : {}) };
}

/** What an applied transition did, in one line. */
export function transitionResultText(
  toLabel: string,
  preview: WorkTransitionPreview | null | undefined,
): string {
  const execution = (preview?.jira_sync_preview?.execution || null) as Record<string, unknown> | null;
  if (!execution || execution.status === "no_driver") return `Moved to ${toLabel}. Nothing was written to Jira.`;
  const parts: string[] = [];
  if (execution.mode === "comment_only") parts.push("comment posted, status unchanged");
  else if (execution.transition_name || execution.resulting_status) {
    parts.push(`transition “${String(execution.transition_name || "")}” → ${String(execution.resulting_status || "")}`.trim());
    parts.push(execution.comment_posted ? "comment posted" : "no comment posted");
  }
  const labels = Array.isArray(execution.labels_applied) ? execution.labels_applied.map(String) : [];
  if (labels.length) parts.push(`labels applied: ${labels.join(", ")}`);
  // Labels are added after the transition; a label failure does not undo it.
  if (execution.labels_failed === true) parts.push("the labels could not be added");
  return `Moved to ${toLabel}. Jira: ${parts.join("; ") || "updated"}.`;
}

/** What a recorded state event wrote to Jira, for the audit timeline. */
export function jiraEffectText(event: WorkStateEvent): string {
  const execution = (event.jira_sync_preview?.execution || null) as Record<string, unknown> | null;
  if (event.dry_run) return "Jira: nothing written (preview).";
  if (!execution || execution.status === "no_driver") return "Jira: nothing written.";
  if (execution.mode === "comment_only") return "Jira: comment posted, status unchanged.";
  const status = execution.resulting_status ? ` → ${String(execution.resulting_status)}` : "";
  const labels = Array.isArray(execution.labels_applied) ? execution.labels_applied.map(String).filter(Boolean) : [];
  const labelsFailed = execution.labels_failed === true ? ", the labels could not be added" : "";
  return `Jira: transition “${String(execution.transition_name || "")}”${status}${execution.comment_posted ? ", comment posted" : ""}${labels.length ? `, labels applied: ${labels.join(", ")}` : ""}${labelsFailed}.`;
}

/** Where workflows are published (Agents › Workflows), in the item's Workspace. */
export function workflowsHref(workspaceId: string | null | undefined): string {
  const query = new URLSearchParams({ area: "workflows", tab: "workflowList" });
  if (workspaceId) query.set("workspace_id", workspaceId);
  return `/chat?${query.toString()}`;
}
