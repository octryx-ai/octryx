// E5 Problems (central configuration, backend): what is
// broken across the platform, each row with the one place to fix it. Pure reading and wording; the server
// aggregates, filters and counts (counts ignore the kind/severity filters, so segment totals stay put).

export const PROBLEM_KINDS = ["connection", "sync", "intake", "run", "rule_denial", "token", "device", "budget"] as const;
export type ProblemKind = (typeof PROBLEM_KINDS)[number];
export type ProblemSeverity = "problem" | "attention";
export type ProblemRef = { id: string; name: string };

export type Problem = {
  key: string;
  kind: ProblemKind | string;
  severity: ProblemSeverity;
  title: string;
  since: string | null;
  lastSeen: string | null;
  count: number;
  workspace: ProblemRef | null;
  object: { type: string; id: string; name: string } | null;
  fix: { label: string; href: string } | null;
};

export type ProblemCounts = { problem: number; attention: number; byKind: Record<string, number> };
export type ProblemList = { problems: Problem[]; counts: ProblemCounts };

export type ProblemFilters = { workspaceId?: string; kind?: string; severity?: string };

export const KIND_LABELS: Record<string, string> = {
  connection: "Connections",
  sync: "Knowledge syncs",
  intake: "Ticket intake",
  run: "Runs",
  rule_denial: "Rule denials",
  token: "Tokens",
  device: "Devices",
  budget: "Budgets",
};

export function kindLabel(kind: string): string {
  return KIND_LABELS[kind] ?? kind.replace(/[_-]+/g, " ").replace(/^./, (char) => char.toUpperCase());
}

const record = (value: unknown): Record<string, unknown> | null =>
  value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : null;
const text = (value: unknown): string => (typeof value === "string" ? value : "");
const number = (value: unknown): number => (typeof value === "number" && Number.isFinite(value) ? value : 0);

function ref(value: unknown): ProblemRef | null {
  const item = record(value);
  return item && text(item.id) ? { id: text(item.id), name: text(item.name) || text(item.id) } : null;
}

/**
 * A fix link only when it stays inside this app: a same-origin path ("/chat?…"). An absolute or protocol-relative
 * URL, or javascript:, is dropped, so a stored value cannot send a person elsewhere.
 */
export function safeFixHref(href: string): string | null {
  const value = href.trim();
  if (!value.startsWith("/") || value.startsWith("//") || value.startsWith("/\\")) return null;
  return value;
}

function readProblem(value: unknown): Problem | null {
  const item = record(value);
  if (!item || !text(item.key) || !text(item.title)) return null;
  const fix = record(item.fix);
  const fixHref = fix ? safeFixHref(text(fix.href)) : null;
  const object = record(item.object);
  return {
    key: text(item.key),
    kind: text(item.kind),
    severity: item.severity === "problem" ? "problem" : "attention",
    title: text(item.title),
    since: text(item.since) || null,
    lastSeen: text(item.last_seen) || null,
    count: Math.max(1, number(item.count)),
    workspace: ref(item.workspace),
    object: object && text(object.id) ? { type: text(object.type), id: text(object.id), name: text(object.name) } : null,
    fix: fix && fixHref ? { label: text(fix.label) || "Open", href: fixHref } : null,
  };
}

export function readProblems(payload: unknown): ProblemList {
  const body = record(payload);
  const problems = (Array.isArray(body?.problems) ? body.problems : [])
    .map(readProblem)
    .filter((problem): problem is Problem => problem !== null);
  const counts = record(body?.counts);
  const byKind: Record<string, number> = {};
  for (const [kind, count] of Object.entries(record(counts?.by_kind) ?? {})) byKind[kind] = number(count);
  return {
    problems,
    counts: {
      problem: counts ? number(counts.problem) : problems.filter((problem) => problem.severity === "problem").length,
      attention: counts ? number(counts.attention) : problems.filter((problem) => problem.severity === "attention").length,
      byKind,
    },
  };
}

/** The query string for the admin list; empty filters are left out. */
export function problemsQuery(filters: ProblemFilters): string {
  const params = new URLSearchParams();
  if (filters.workspaceId) params.set("workspace_id", filters.workspaceId);
  if (filters.kind) params.set("kind", filters.kind);
  if (filters.severity) params.set("severity", filters.severity);
  const query = params.toString();
  return query ? `?${query}` : "";
}

/** The kind segments: All plus every kind the server counted (in a fixed order), with their totals. */
export function kindTabs(counts: ProblemCounts): { key: string; label: string; count: number }[] {
  const total = counts.problem + counts.attention;
  const present = [
    ...PROBLEM_KINDS.filter((kind) => counts.byKind[kind] > 0),
    ...Object.keys(counts.byKind).filter((kind) => !(PROBLEM_KINDS as readonly string[]).includes(kind) && counts.byKind[kind] > 0),
  ];
  return [{ key: "", label: "All", count: total }, ...present.map((kind) => ({ key: kind, label: kindLabel(kind), count: counts.byKind[kind] }))];
}

// The kind segments already start with "All"; the severity group's own first segment says what it does not filter
// (two adjacent "All" segments).
export function severityTabs(counts: ProblemCounts): { key: string; label: string; count: number }[] {
  return [
    { key: "", label: "Any severity", count: counts.problem + counts.attention },
    { key: "problem", label: "Problems", count: counts.problem },
    { key: "attention", label: "Attention", count: counts.attention },
  ];
}

export function severityLabel(severity: ProblemSeverity): { label: string; tone: "problem" | "attention" } {
  return severity === "problem" ? { label: "Problem", tone: "problem" } : { label: "Attention", tone: "attention" };
}

export function countText(count: number): string {
  return count > 1 ? `${count}×` : "once";
}

/** Server refusals in one sentence each; an unknown code keeps the server's own message. */
export function refusalText(status: number, code: string, message: string): string {
  if (code === "problem_not_found") return "This problem is no longer open.";
  if (code === "admin_required" || (!code && status === 403)) return "Only admins can see the problems of the platform.";
  if (code === "workspace_not_found" || (!code && status === 404)) return "This Workspace is not visible to you.";
  if (code === "invalid_filter" || (!code && status === 422)) return "This filter is not known. Choose All to see every problem.";
  return message || "The problems could not be loaded.";
}
