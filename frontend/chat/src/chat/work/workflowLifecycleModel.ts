import type { ProjectOption } from "../../chatOptionTypes";
import { workStateLabel } from "./workBoardColumns";
import type { WorkWorkflowDefinition } from "./workSyncWorkflowTypes";
import { SYNC_MODE_DRY_RUN, SYNC_MODE_EXECUTE, policyWithSyncMode, sourceStatusOf, sourceTransitionOf, syncModeOf } from "./syncNames";

// Workflow management in Work → Jira write-back (work-settings-workflows-ui B-6). Pure: no React.
//
// A workflow either only previews (`sync_policy.sync_mode` other than "execute": nothing is written to Jira) or
// executes (applies write to Jira for every state whose mapping sets `sync_back`). Changing the mode or the active
// state goes through an explicit confirmation that says exactly what will, or will no longer, be written.

export type WorkflowMode = "execute" | "dry_run";

export function workflowMode(workflow: WorkWorkflowDefinition): WorkflowMode {
  return syncModeOf(workflow.sync_policy) === SYNC_MODE_EXECUTE ? "execute" : "dry_run";
}

export function workflowModeLabel(mode: WorkflowMode): string {
  return mode === "execute" ? "Executes in the source" : "Dry-run only";
}

/** One mapped state: the whole write in words (`writes`, for confirmations) and its parts under the neutral names. */
export type MappingRow = {
  state: string;
  label: string;
  writes: string;
  status: string;
  transition: string;
  extras: string;
  syncBack: boolean;
};

const named = (value: unknown) => (typeof value === "string" && value.trim() ? value.trim() : "");

/** What a mapping writes to Jira, in words ("status In Progress · comment “…” · labels octryx"), or "" when nothing. */
export function mappingWrites(mapping: WorkWorkflowDefinition["mappings"][string] | undefined): string {
  if (!mapping) return "";
  const status = sourceStatusOf(mapping);
  const transition = sourceTransitionOf(mapping);
  const parts = [
    status ? `status ${status}` : transition ? `transition “${transition}”` : "",
    status && transition ? `via “${transition}”` : "",
    mappingExtras(mapping),
  ].filter(Boolean);
  return parts.join(" · ");
}

/** What a mapping writes besides the status: the comment and the labels. */
function mappingExtras(mapping: WorkWorkflowDefinition["mappings"][string]): string {
  return [
    named(mapping.comment_template) ? `comment “${named(mapping.comment_template)}”` : "",
    Array.isArray(mapping.labels) && mapping.labels.length ? `labels ${mapping.labels.join(", ")}` : "",
  ].filter(Boolean).join(" · ");
}

/** One row per workflow state that has a mapping: work state ↔ what Jira gets, and whether it syncs back. */
export function mappingSummary(workflow: WorkWorkflowDefinition): MappingRow[] {
  const mappings = workflow.mappings || {};
  // The server normalises mappings to one per state; a state that writes nothing and does not sync back is no mapping.
  return (workflow.states || [])
    .filter((state) => mappings[state.key] && (mappings[state.key]?.sync_back === true || mappingWrites(mappings[state.key])))
    .map((state) => ({
      state: state.key,
      label: state.label || workStateLabel(state.key, [workflow]),
      writes: mappingWrites(mappings[state.key]) || "nothing",
      status: sourceStatusOf(mappings[state.key]),
      transition: sourceTransitionOf(mappings[state.key]),
      extras: mappingExtras(mappings[state.key]),
      syncBack: mappings[state.key]?.sync_back === true,
    }));
}

/** The Jira writes an execute workflow makes: the sync-back rows that write something. */
export function executeWrites(workflow: WorkWorkflowDefinition): MappingRow[] {
  return mappingSummary(workflow).filter((row) => row.syncBack && row.writes !== "nothing");
}

export type Confirmation = { title: string; lines: string[]; confirmLabel: string; danger: boolean };

/** The confirmation of switching the mode, listing what will (or will no longer) be written. */
export function modeSwitchConfirmation(workflow: WorkWorkflowDefinition): Confirmation {
  const toExecute = workflowMode(workflow) !== "execute";
  const writes = executeWrites(workflow);
  if (toExecute) {
    return {
      title: `Switch “${workflow.name}” to execute in Jira?`,
      lines: writes.length
        ? [
            "Applying a transition will then write to Jira:",
            ...writes.map((row) => `${row.label}: ${row.writes}`),
            "Each apply still needs its own preview and confirmation.",
          ]
        : ["No state of this workflow syncs back to Jira yet, so nothing is written until a mapping sets sync-back."],
      confirmLabel: "Switch to execute",
      danger: true,
    };
  }
  return {
    title: `Switch “${workflow.name}” to dry-run only?`,
    lines: [
      "Jira will no longer be written by this workflow: applies change only Octryx, previews keep working.",
      ...(writes.length ? [`It stops writing: ${writes.map((row) => row.label).join(", ")}.`] : []),
    ],
    confirmLabel: "Switch to dry-run only",
    danger: false,
  };
}

/** The confirmation of activating or deactivating; deactivating an execute workflow says Jira is no longer written. */
export function activationConfirmation(workflow: WorkWorkflowDefinition): Confirmation {
  if (workflow.is_active) {
    return {
      title: `Deactivate “${workflow.name}”?`,
      lines: [
        "Items can no longer be moved with it: previews and applies are refused until it is activated again.",
        ...(workflowMode(workflow) === "execute"
          ? ["It executes in Jira, so Jira will no longer be written through it."]
          : []),
      ],
      confirmLabel: "Deactivate",
      danger: true,
    };
  }
  return {
    title: `Activate “${workflow.name}”?`,
    lines: [
      workflowMode(workflow) === "execute"
        ? "Items can be moved with it again, and applies write to Jira (it executes in Jira)."
        : "Items can be moved with it again; it previews only and writes nothing to Jira.",
    ],
    confirmLabel: "Activate",
    danger: false,
  };
}

/** The sync policy for the other mode, under the neutral name and its Jira alias; every other key is kept. */
export function switchedPolicy(workflow: WorkWorkflowDefinition): Record<string, unknown> {
  return policyWithSyncMode(workflow.sync_policy, workflowMode(workflow) === "execute" ? SYNC_MODE_DRY_RUN : SYNC_MODE_EXECUTE);
}

export type WorkflowGroup = { key: string; title: string; workflows: WorkWorkflowDefinition[] };

/** Workflows per Workspace (by name), the Workspace-independent ones last as "All Workspaces". */
export function workflowGroups(workflows: WorkWorkflowDefinition[], projects: ProjectOption[]): WorkflowGroup[] {
  const groups = new Map<string, WorkflowGroup>();
  for (const workflow of workflows) {
    const key = workflow.project_id || "";
    if (!groups.has(key)) {
      const title = key ? projects.find((project) => project.id === key)?.name || key : "All Workspaces";
      groups.set(key, { key, title, workflows: [] });
    }
    groups.get(key)!.workflows.push(workflow);
  }
  return Array.from(groups.values()).sort((left, right) =>
    left.key === right.key ? 0 : !left.key ? 1 : !right.key ? -1 : left.title.localeCompare(right.title),
  );
}

/** A refused change, in words: the server's message (403 names the missing right). */
/** r8: a 409 that is a version conflict (someone saved the workflow after this page loaded it). */
export function isStaleRefusal(error: unknown): boolean {
  const record = error && typeof error === "object" ? (error as { status?: unknown; code?: unknown }) : null;
  if (record?.status !== 409) return false;
  return !record.code || (typeof record.code === "string" && record.code.includes("stale"));
}

export function workflowRefusalText(error: unknown): string {
  const record = error && typeof error === "object" ? (error as { message?: unknown; status?: unknown }) : null;
  if (record?.status === 403) return "You may not change this Workspace's workflows (Workspace admin or owner needed).";
  if (isStaleRefusal(error)) {
    return "Not saved: this workflow was changed after this page loaded it. The list was reloaded; check it and confirm again.";
  }
  const message = typeof record?.message === "string" && record.message ? record.message : "The change was not saved.";
  return `Not saved: ${message}`;
}
