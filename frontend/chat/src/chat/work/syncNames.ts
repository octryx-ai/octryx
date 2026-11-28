export const SYNC_MODE_EXECUTE = "execute";
export const SYNC_MODE_DRY_RUN = "dry_run_only";

const LABELS: Record<string, string> = {
  source_status: "Status in the source",
  source_transition: "Transition used to write back",
  sync_mode: "Sync",
};

export const neutralLabel = (key: string): string => LABELS[key] ?? "";

type MappingNames = { source_status?: unknown; source_transition?: unknown };

const named = (value: unknown) => (typeof value === "string" && value.trim() ? value.trim() : "");

export const sourceStatusOf = (mapping: MappingNames | null | undefined): string => named(mapping?.source_status);

export const sourceTransitionOf = (mapping: MappingNames | null | undefined): string =>
  named(mapping?.source_transition);

export function syncModeOf(policy: Record<string, unknown> | null | undefined): string {
  return named(policy?.sync_mode);
}

export function policyWithSyncMode(policy: Record<string, unknown> | null | undefined, mode: string): Record<string, unknown> {
  return { ...(policy || {}), sync_mode: mode };
}
