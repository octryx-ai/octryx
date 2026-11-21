// Safe defaults of the new-agent form. A new agent starts with the
// least-privileged mode the catalog offers and inactive until its author
// deliberately activates it. Agents are Global: the form sends no workspace.

export type AgentModeLike = {
  key: string;
  name?: string;
  capability_type?: string;
  is_active?: boolean;
};

// Capability types of the backend mode catalog (agent/runtime_defaults.py),
// ordered from least to most privileged.
const CAPABILITY_RANK: Record<string, number> = {
  diagnosis: 0,
  plan: 1,
  change: 2,
  admin: 3,
};

const READ_ONLY_CAPABILITIES = new Set(["diagnosis", "plan"]);

export const NEW_AGENT_DEFAULTS = {
  thinking: "light",
  branchPrefix: "octryx",
  isActive: false,
} as const;

export function capabilityLabel(capability: string | undefined): string {
  switch (capability) {
    case "diagnosis":
      return "Read-only";
    case "plan":
      return "Plans, read-only";
    case "change":
      return "Can make changes";
    case "admin":
      return "Full platform control";
    default:
      return "Unknown permissions";
  }
}

// The least-privileged active mode: the `diagnosis` system mode when present,
// otherwise the first read-only mode in catalog order. Returns "" when the
// catalog has no read-only mode, so the author must choose explicitly.
export function resolveSafeDefaultMode(modes: AgentModeLike[]): string {
  const active = modes.filter((mode) => mode.key && mode.is_active !== false);
  const readOnly = active
    .filter((mode) => READ_ONLY_CAPABILITIES.has(String(mode.capability_type)))
    .map((mode, index) => ({ mode, index }))
    .sort((left, right) => {
      const rank =
        CAPABILITY_RANK[String(left.mode.capability_type)] -
        CAPABILITY_RANK[String(right.mode.capability_type)];
      return rank || left.index - right.index;
    })
    .map((entry) => entry.mode);
  const diagnosis = readOnly.find(
    (mode) => mode.key === "diagnosis" && mode.capability_type === "diagnosis",
  );
  return (diagnosis ?? readOnly[0])?.key ?? "";
}
