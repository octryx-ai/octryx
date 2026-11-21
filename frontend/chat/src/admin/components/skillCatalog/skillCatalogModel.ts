// The skill catalog page model: response types of the admin API, refusal texts and the small display
// helpers every view shares. Pure functions only (unit-tested in tests/unit/skillCatalogModel.test.mjs).

import { REFUSALS } from "./skillCatalogRefusals";
import type { CategoryNode, MergeReport, SkillRow, SourceRef, VersionState } from "./skillCatalogTypes";
import type { Readiness } from "./skillDeliveryTypes";

// ---- refusals -------------------------------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function refusalText(error: unknown): string {
  const value = isRecord(error) ? error : {};
  const code = typeof value.code === "string" ? value.code : "";
  if (code && REFUSALS[code]) return REFUSALS[code];
  if (value.status === 403) return "Platform admin role required.";
  const message = error instanceof Error ? error.message : typeof value.message === "string" ? value.message : "";
  return message ? `Refused: ${message}.` : "The request failed.";
}

// ---- display helpers -------------------------------------------------------------------------------------------

export const STATE_LABELS: Record<VersionState, string> = { draft: "Draft", in_review: "In review", published: "Published", retired: "Retired" };
const STATE_BADGES: Record<VersionState, string> = { draft: "attention", in_review: "running", published: "active", retired: "neutral" };

/** `work-badge` modifier of a version state (published active, draft attention, in review running, retired neutral). */
export function stateBadge(state: string): string {
  return `work-badge work-badge--${STATE_BADGES[state as VersionState] ?? "neutral"}`;
}

/** The row's version cell: the published version, plus the open one when there is one. */
export function versionLine(row: Pick<SkillRow, "published" | "open">): string {
  const parts: string[] = [];
  if (row.published) parts.push(`v${row.published.version}`);
  if (row.open) parts.push(`v${row.open.version} ${STATE_LABELS[row.open.state].toLowerCase()}`);
  return parts.length ? parts.join(" · ") : "retired";
}

export function trustLabel(source: Pick<SourceRef, "trust" | "kind"> | null): string {
  if (!source) return "Written here";
  if (source.kind === "upload") return "Uploaded";
  return source.trust === "official" ? "Official" : source.trust === "internal" ? "Internal" : "Community";
}

export function shortCommit(commit: string | null | undefined): string {
  return commit ? commit.slice(0, 8) : "—";
}

export function shortDigest(digest: string | null | undefined): string {
  if (!digest) return "—";
  const hex = digest.replace(/^sha256:/, "");
  return `sha256:${hex.slice(0, 4)}…${hex.slice(-2)}`;
}

export function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

const ASSIGNED_BY: Record<string, string> = { all: "All published", skill: "Selected skill" };

/** `all` | `skill` | `category:<key>` → a label; `labels` maps category keys to their labels. */
export function assignedByLabel(assignedBy: string, labels: Record<string, string> = {}): string {
  if (assignedBy.startsWith("category:")) {
    const key = assignedBy.slice("category:".length);
    return `Category ${labels[key] ?? key}`;
  }
  return ASSIGNED_BY[assignedBy] ?? "Not assigned";
}

const REASONS: Record<string, string> = {
  not_available_on_surface: "Not available on this surface",
  surface_off_for_workspace: "Surface switched off in this Workspace",
  skills_off_for_workspace: "Workspace receives no catalog skills",
  not_assigned: "Not assigned",
  blocked_by_workspace: "Blocked in this Workspace",
  blocked_by_agent: "Blocked for the agent",
  role_not_allowed: "Role not allowed",
  needs_mcp_policy: "Needs MCP policy",
  image_digest_missing: "Image digest missing",
  name_not_deliverable: "Name outside the Agent Skills spec",
  plugin_not_installed_here: "Plugin is not switched on in this Workspace",
};

export function reasonLabel(reason: string): string {
  return REASONS[reason] ?? reason.replace(/_/g, " ");
}

export function readinessBadge(readiness: Readiness | null | undefined): { label: string; className: string } {
  if (!readiness) return { label: "—", className: "work-badge work-badge--neutral" };
  if (readiness.state === "ready") return { label: "Ready", className: "work-badge work-badge--active" };
  if (readiness.state === "needs_mcp_policy") return { label: "Needs MCP policy", className: "work-badge work-badge--attention" };
  return { label: "Restricted", className: "work-badge work-badge--attention" };
}

/** Every category flattened in tree order, with its depth and full label (for selects and lookups). */
export function flattenCategories(nodes: CategoryNode[]): (CategoryNode & { depth: number; fullLabel: string })[] {
  const rows: (CategoryNode & { depth: number; fullLabel: string })[] = [];
  for (const node of nodes) {
    rows.push({ ...node, depth: 0, fullLabel: node.label });
    for (const child of node.children) rows.push({ ...child, depth: 1, fullLabel: `${node.label} / ${child.label}` });
  }
  return rows;
}

export function categoryLabels(nodes: CategoryNode[]): Record<string, string> {
  return Object.fromEntries(flattenCategories(nodes).map((node) => [node.key, node.fullLabel]));
}

/** Uses split by surface for the usage table: chat gets, octryx-claude model / slash. */
export function usageSplit(bySurface: Record<string, number>): { chat: number; model: number; slash: number } {
  return {
    chat: (bySurface["platform_chat:get"] ?? 0) + (bySurface["platform_chat:use"] ?? 0),
    model: bySurface["octryx_claude:model"] ?? 0,
    slash: bySurface["octryx_claude:slash"] ?? 0,
  };
}

/** Split a SKILL.md into its frontmatter block and body (display only; the server is the parser of record). */
export function splitSkillMd(text: string): { frontmatter: string; body: string } {
  const match = /^---[ \t]*\r?\n([\s\S]*?)\r?\n---[ \t]*(?:\r?\n|$)/.exec(text);
  if (!match) return { frontmatter: "", body: text };
  return { frontmatter: match[1], body: text.slice(match[0].length) };
}

/** Agent Skills name rule (spec): 1–64 chars of a-z0-9 and single hyphens, no hyphen at either end. */
export function nameIssue(name: string): string | null {
  if (!name) return "Give the skill a name.";
  if (name.length > 64) return "At most 64 characters.";
  if (!/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(name)) return "Use lower-case letters, digits and single hyphens; no hyphen at the start or end.";
  return null;
}

export function descriptionIssue(description: string): string | null {
  if (!description.trim()) return "Describe what the skill does and when to use it.";
  if (description.length > 1024) return "At most 1024 characters.";
  return null;
}

export function hasOpenConflicts(report: MergeReport | null | undefined): boolean {
  if (!report) return false;
  return report.conflicts.some((conflict) => !report.resolutions?.[conflict.id]);
}

