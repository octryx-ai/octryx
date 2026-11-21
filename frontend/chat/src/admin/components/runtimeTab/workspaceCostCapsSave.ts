// Workspace cost-cap overrides (runtime audit P-7). Each cap is either an override (a
// number; 0 turns the cap off for this Workspace) or "inherit", which removes the
// override so the platform value applies again. An empty field is never guessed into
// either: the admin must type a number or choose inherit.
//
// Backend contract (services/budget/project_cost_limits.py): a cap sent with a value
// sets it, a cap listed in `inherit_cost_limits` is removed, an unnamed cap is unchanged.
// The platform level keeps its own semantics (0 or empty = no cap) and has no inherit.

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

/** A cap inherits when the Workspace has no override for it. */
export function costCapInheritFromScope(scope: CostCapScope): CostCapInherit {
  return {
    [SESSION_COST_CAP]: scope?.session_source !== "project",
    [REQUEST_COST_CAP]: scope?.request_source !== "project",
  };
}

/** The exact PUT body, or the cap whose override is empty (nothing may be written then). */
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
