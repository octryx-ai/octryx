// Workspace › Connections › narrow: a
// connection is defined once globally; a workspace uses it and may only narrow it — fewer spaces/projects, a use
// switched off, a lower agent tools level. Data: GET /api/v1/workspaces/{ws}/connections ({base, effective,
// deviation}); save: PUT …/{id}/deviation with only what differs from base; reset: DELETE …/{id}/deviation.

export type UseValues = { enabled?: boolean; scope?: Record<string, string[]> | null; schedule?: string; [key: string]: unknown };
export type ConnectionValues = { knowledge?: UseValues; tickets?: UseValues; agent_tools?: { level?: string } };

export type WorkspaceConnection = {
  id: string;
  name: string;
  type: string;
  state: string;
  base?: ConnectionValues | null;
  effective: ConnectionValues | null;
  deviation: ConnectionValues | null;
  can_edit: boolean;
};

export type NarrowDraft = {
  knowledge?: { enabled: boolean; items: string[] };
  tickets?: { enabled: boolean; items: string[] };
  level?: string;
};

export const SCOPED_USES = ["knowledge", "tickets"] as const;
export type ScopedUse = (typeof SCOPED_USES)[number];
export const USE_LABELS: Record<ScopedUse, string> = { knowledge: "Knowledge sync", tickets: "Tickets" };
export const LEVELS = ["off", "read", "write"] as const;
export const LEVEL_LABELS: Record<string, string> = {
  off: "Agents may not use it",
  read: "Agents may read",
  write: "Agents may read and write (with approval)",
};

export const connectionsPath = (workspaceId: string) => `/api/v1/workspaces/${encodeURIComponent(workspaceId)}/connections`;
export const deviationPath = (workspaceId: string, connectionId: string) =>
  `${connectionsPath(workspaceId)}/${encodeURIComponent(connectionId)}/deviation`;

/** The scope key ("spaces", "projects") and its items of a use; null when the use has no scope. */
export function scopeOf(values: UseValues | undefined): { key: string; items: string[] } | null {
  const scope = values?.scope;
  if (!scope || typeof scope !== "object") return null;
  const key = Object.keys(scope)[0];
  return key ? { key, items: [...(scope[key] ?? [])] } : null;
}

/** "spaces" → "Spaces". */
export function scopeTitle(key: string): string {
  return key ? key[0].toUpperCase() + key.slice(1) : "Scope";
}

/** The draft from what applies now. */
export function draftOf(connection: WorkspaceConnection): NarrowDraft {
  const draft: NarrowDraft = {};
  for (const use of SCOPED_USES) {
    const values = connection.effective?.[use];
    if (!connection.base?.[use] || !values) continue;
    draft[use] = { enabled: Boolean(values.enabled), items: scopeOf(values)?.items ?? [] };
  }
  const level = connection.effective?.agent_tools?.level;
  if (level) draft.level = level;
  return draft;
}

/** The levels a workspace may choose: up to the global one. */
export function levelOptions(base: string | undefined): string[] {
  const top = LEVELS.indexOf((base ?? "off") as (typeof LEVELS)[number]);
  return LEVELS.slice(0, Math.max(top, 0) + 1);
}

const same = (left: string[], right: string[]) =>
  left.length === right.length && left.every((item) => right.map((value) => value.toUpperCase()).includes(item.toUpperCase()));

/** The deviation to store: only what differs from the global values; null when nothing does. */
export function deviationOf(base: ConnectionValues | null | undefined, draft: NarrowDraft): ConnectionValues | null {
  const result: ConnectionValues = {};
  for (const use of SCOPED_USES) {
    const wanted = draft[use];
    const global = base?.[use];
    if (!wanted || !global) continue;
    const fields: UseValues = {};
    if (Boolean(global.enabled) && !wanted.enabled) fields.enabled = false;
    const scope = scopeOf(global);
    // A use switched off keeps no scope of its own: switched on again, it starts from the global one.
    if (scope && wanted.enabled && !same(wanted.items, scope.items)) fields.scope = { [scope.key]: wanted.items };
    if (Object.keys(fields).length) result[use] = fields;
  }
  if (draft.level && base?.agent_tools?.level && draft.level !== base.agent_tools.level) {
    result.agent_tools = { level: draft.level };
  }
  return Object.keys(result).length ? result : null;
}

/** How many fields a deviation changes: "2 changes from global". */
export function changeCount(deviation: ConnectionValues | null | undefined): number {
  if (!deviation) return 0;
  return Object.values(deviation).reduce((sum, fields) => sum + Object.keys(fields ?? {}).length, 0);
}

export function changeText(deviation: ConnectionValues | null | undefined): string {
  const count = changeCount(deviation);
  if (!count) return "Inherited from global";
  return `${count} change${count === 1 ? "" : "s"} from global`;
}

/** "Narrowed" next to a field this workspace changed, else "Inherited". */
export function fieldState(deviation: ConnectionValues | null | undefined, use: keyof ConnectionValues, field: string): "Narrowed" | "Inherited" {
  const fields = deviation?.[use] as Record<string, unknown> | undefined;
  return fields && field in fields ? "Narrowed" : "Inherited";
}

/** A scope left empty would switch the use off silently; the page says so instead. Only where the global connection
 * has a scope to pick from (a connection without one, e.g. Bitbucket has nothing to narrow there). */
export function draftProblem(draft: NarrowDraft, base?: ConnectionValues | null): string | null {
  for (const use of SCOPED_USES) {
    const wanted = draft[use];
    const offered = scopeOf(base?.[use])?.items.length ?? 0;
    if (wanted?.enabled && offered > 0 && wanted.items.length === 0) return `${USE_LABELS[use]}: pick at least one, or switch it off.`;
  }
  return null;
}
