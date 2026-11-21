// Configured versus visible keys of a connection test (delivery 5): the server's `scope_check`
// (services/connector_test/scope_check.py) as lines an admin can act on. Pure: no React.

export type ScopeCheck = {
  label: string; // "Spaces"
  noun: string; // "space"
  configured: string[] | null; // null: no restriction configured (e.g. Jira without a project list)
  visible: string[];
  visibleCount: number;
  visibleComplete: boolean;
  missing: string[];
  error: string | null;
  httpStatus: number | null;
};

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];

export function scopeCheckOf(result: unknown): ScopeCheck | null {
  const raw = (result as { scope_check?: unknown } | null)?.scope_check;
  if (!raw || typeof raw !== "object") return null;
  const check = raw as Record<string, unknown>;
  if (typeof check.label !== "string" || typeof check.noun !== "string") return null;
  return {
    label: check.label,
    noun: check.noun,
    configured: Array.isArray(check.configured) ? strings(check.configured) : null,
    visible: strings(check.visible),
    visibleCount: typeof check.visible_count === "number" ? check.visible_count : strings(check.visible).length,
    visibleComplete: check.visible_complete === true,
    missing: strings(check.missing),
    error: typeof check.error === "string" ? check.error : null,
    httpStatus: typeof check.http_status === "number" ? check.http_status : null,
  };
}

export type ScopeLine = { key: string; visible: boolean; text: string };

/** One line per configured key: visible to the account, or configured but not visible. */
export function configuredLines(check: ScopeCheck): ScopeLine[] {
  const noun = check.noun.charAt(0).toUpperCase() + check.noun.slice(1);
  return (check.configured ?? []).map((key) => {
    const visible = !check.missing.includes(key);
    return {
      key,
      visible,
      text: visible ? `${noun} ${key}: visible to this account.` : `${noun} ${key}: configured but not visible to this account.`,
    };
  });
}

/** What the account sees, bounded: "This account sees 3 spaces: A, B, C." */
export function visibleText(check: ScopeCheck): string {
  const plural = check.label.toLowerCase();
  if (check.error) {
    return `The visible ${plural} could not be listed (${check.error}${check.httpStatus ? `, HTTP ${check.httpStatus}` : ""}).`;
  }
  if (check.visibleCount === 0) return `This account sees no ${plural}.`;
  const shown = check.visible.join(", ");
  const more = check.visibleCount > check.visible.length ? `, … (${check.visibleCount} in total)` : "";
  const cut = check.visibleComplete ? "" : " The listing was cut; configured keys were checked one by one.";
  const counted = check.visibleCount === 1 ? check.noun : plural;
  return `This account sees ${check.visibleCount} ${counted}: ${shown}${more}.${cut}`;
}

/** Missing keys as tag flags (key → reason) for a tag input. */
export function missingFlags(check: ScopeCheck | null): Record<string, string> {
  return Object.fromEntries((check?.missing ?? []).map((key) => [key, "Configured but not visible to this account"]));
}
