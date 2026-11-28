// An empty field is never guessed into a number or inherit: the admin must choose.

export const SESSION_COST_CAP = "agent_session_cost_limit_usd";
export const REQUEST_COST_CAP = "agent_request_cost_limit_usd";
export type CostCapKey = typeof SESSION_COST_CAP | typeof REQUEST_COST_CAP;

export type CostCapInherit = Record<CostCapKey, boolean>;

export type WorkspaceCostCapsPayload = Partial<Record<CostCapKey, number>> & {
  inherit_cost_limits: CostCapKey[];
};

export const MISSING_OVERRIDE_ERROR =
  "Enter a cap (0 turns it off for this workspace) or choose Inherit platform value.";

type CostCapScope = { session_source?: string; request_source?: string } | null | undefined;

export function costCapInheritFromScope(scope: CostCapScope): CostCapInherit {
  return {
    [SESSION_COST_CAP]: scope?.session_source !== "project",
    [REQUEST_COST_CAP]: scope?.request_source !== "project",
  };
}

export function buildWorkspaceCostCapsPayload(
  values: Record<CostCapKey, string>,
  inherit: CostCapInherit,
): { payload: WorkspaceCostCapsPayload } | { error: string; cap: CostCapKey } {
  const payload: WorkspaceCostCapsPayload = { inherit_cost_limits: [] };
  for (const cap of [SESSION_COST_CAP, REQUEST_COST_CAP] as const) {
    if (inherit[cap]) {
      payload.inherit_cost_limits.push(cap);
      continue;
    }
    const text = String(values[cap] ?? "").trim();
    if (!text) return { error: MISSING_OVERRIDE_ERROR, cap };
    payload[cap] = Number(text);
  }
  return { payload };
}
