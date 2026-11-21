// The Workspace's standing tool approvals ("Always for this Workspace" on
// a tool approval). Server contract (backend services/standing_approvals/tool_rules.py):
// `standing_tool_approvals: {rules: [{tool_name, argument_class, granted_by, granted_at}]}`.
// A rule covers the tool (or approval subject) plus, for command tools, the
// exec-policy argument class (`git status`, `kubectl get`, `npm`). An admin
// revokes a rule here; the write is the audited project-config write.

export const STANDING_TOOL_APPROVALS_KEY = "standing_tool_approvals";

export type StandingToolRule = {
  toolName: string;
  argumentClass: string | null;
  grantedBy: string | null;
  grantedAt: string | null;
};

function rawRules(config: unknown): unknown[] {
  const section =
    config && typeof config === "object"
      ? (config as Record<string, unknown>)[STANDING_TOOL_APPROVALS_KEY]
      : undefined;
  const rules =
    section && typeof section === "object"
      ? (section as Record<string, unknown>).rules
      : undefined;
  return Array.isArray(rules) ? rules : [];
}

function text(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

export function standingToolRules(config: unknown): StandingToolRule[] {
  return rawRules(config).flatMap((entry) => {
    if (!entry || typeof entry !== "object") return [];
    const record = entry as Record<string, unknown>;
    const toolName = text(record.tool_name);
    if (!toolName) return [];
    return [
      {
        toolName,
        argumentClass: text(record.argument_class),
        grantedBy: text(record.granted_by),
        grantedAt: text(record.granted_at),
      },
    ];
  });
}

export function standingToolRuleLabel(
  rule: Pick<StandingToolRule, "toolName" | "argumentClass">,
): string {
  return rule.argumentClass
    ? `${rule.toolName} · ${rule.argumentClass}`
    : rule.toolName;
}

// The PUT body that removes exactly one rule (same tool and argument class).
export function revokeStandingToolRulePatch(
  config: unknown,
  rule: Pick<StandingToolRule, "toolName" | "argumentClass">,
) {
  const remaining = rawRules(config).filter((entry) => {
    if (!entry || typeof entry !== "object") return false;
    const record = entry as Record<string, unknown>;
    return !(
      record.tool_name === rule.toolName &&
      (text(record.argument_class) ?? null) === rule.argumentClass
    );
  });
  return { [STANDING_TOOL_APPROVALS_KEY]: { rules: remaining } };
}
