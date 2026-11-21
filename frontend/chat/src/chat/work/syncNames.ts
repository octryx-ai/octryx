// Source-neutral names of the write-back settings (backend `sync_policy.py`): a workflow mapping says
// `source_status` / `source_transition` and its policy `sync_mode`, the same for Jira, ServiceNow and Custom REST.
// Pure: no React.

export const SYNC_MODE_EXECUTE = "execute";
export const SYNC_MODE_DRY_RUN = "dry_run_only";

const LABELS: Record<string, string> = {
  source_status: "Status in the source",
  source_transition: "Transition used to write back",
  sync_mode: "Sync",
};

/** The words a write-back key reads as, the same for every source; "" for a key that is not a write-back name. */
export const neutralLabel = (key: string): string => LABELS[key] ?? "";

type MappingNames = { source_status?: unknown; source_transition?: unknown };

const named = (value: unknown) => (typeof value === "string" && value.trim() ? value.trim() : "");

/** The status a state writes to the source. */
export const sourceStatusOf = (mapping: MappingNames | null | undefined): string => named(mapping?.source_status);

/** The transition a state uses to write back. */
export const sourceTransitionOf = (mapping: MappingNames | null | undefined): string =>
  named(mapping?.source_transition);

/** The policy's sync mode (`sync_mode`, backend `sync_policy.sync_mode`). */
export function syncModeOf(policy: Record<string, unknown> | null | undefined): string {
  return named(policy?.sync_mode);
}

/** The policy with a new sync mode. */
export function policyWithSyncMode(policy: Record<string, unknown> | null | undefined, mode: string): Record<string, unknown> {
  return { ...(policy || {}), sync_mode: mode };
}
