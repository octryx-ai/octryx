import type { AdminProjectQuality } from "../../types/projectQualityTypes";

// One Workspaces-list row (central configuration, UX review "Workspace list in the new style"): name with its
// badges and description as tooltip, the Workspace's class, members, problems and last change. Agent templates and
// design readiness left the list; a row opens the Workspace page. Class, members and the change time are read when
// the list payload carries them (class / member_count / updated_at); the list shows "—" otherwise.
export const WORKSPACE_LIST_COLUMN_LABELS = {
  workspace: "Name",
  class: "Class",
  members: "Members",
  problems: "Problems",
  updated: "Updated",
  actions: "Actions",
} as const;

export const CLASS_LABELS: Record<string, string> = {
  public: "Public",
  internal: "Internal",
  confidential: "Confidential",
  restricted: "Restricted",
  secret: "Secret",
};

export type WorkspaceListRow = {
  id: string;
  name: string;
  badges: string[];
  // Whitespace-collapsed text for the clamped line; the full text goes in `title`.
  description: string;
  descriptionTitle: string;
  isActive: boolean;
  statusLabel: "Active" | "Inactive";
  classLabel: string;
  members: number | null;
  updatedAt: string | null;
};

type WorkspaceRowSource = Pick<AdminProjectQuality, "id" | "name" | "description" | "is_active"> &
  Partial<Pick<AdminProjectQuality, "is_system" | "is_default" | "template_key">> & {
    class?: unknown;
    workspace_class?: unknown;
    member_count?: unknown;
    members_count?: unknown;
    updated_at?: unknown;
  };

/** The words for a classification level ("confidential" → "Confidential"). */
export function classLabelOf(level: string): string {
  return CLASS_LABELS[level] ?? level.replace(/^./, (char) => char.toUpperCase());
}

function classOf(project: WorkspaceRowSource): string {
  const raw = typeof project.class === "string" ? project.class : typeof project.workspace_class === "string" ? project.workspace_class : "";
  return raw ? classLabelOf(raw) : "—";
}

// Each active Workspace's classification level and where it came from (GET /api/v1/admin/data-classification/policy/
// workspaces, platform admins): `workspace` its own, `instance_default` the default, `unset` none.
export type WorkspaceClasses = Record<string, { level: string | null; source: string }>;

export function readWorkspaceClasses(payload: unknown): WorkspaceClasses {
  const rows = payload && typeof payload === "object" ? (payload as { workspaces?: unknown }).workspaces : null;
  const classes: WorkspaceClasses = {};
  for (const item of Array.isArray(rows) ? rows : []) {
    if (!item || typeof item !== "object" || typeof item.id !== "string") continue;
    classes[item.id] = { level: typeof item.level === "string" && item.level ? item.level : null,
      source: typeof item.source === "string" ? item.source : "" };
  }
  return classes;
}

/**
 * The Class cell (UI check C7: "—" stood in every row). A known level in words; "Not set" with Set class
 * when the Workspace has none; Show class when the level cannot be read here (no admin view of the levels, or an
 * archived Workspace). Never a bare dash.
 */
export type WorkspaceClassCell = { label: string; title: string; action: "set" | "show" | null };

export function workspaceClassCell(row: Pick<WorkspaceListRow, "id" | "classLabel" | "isActive">,
  classes: WorkspaceClasses | null): WorkspaceClassCell {
  const known = classes?.[row.id];
  if (known?.level) {
    return { label: classLabelOf(known.level), action: null,
      title: known.source === "instance_default" ? "From the instance default" : "" };
  }
  if (row.classLabel !== "—") return { label: row.classLabel, title: "", action: null };
  if (known || (classes && row.isActive)) return { label: "Not set", title: "This Workspace has no data classification yet.", action: "set" };
  return { label: "", title: "", action: "show" };
}

function countOf(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : null;
}

export function workspaceListRow(project: WorkspaceRowSource): WorkspaceListRow {
  const rawDescription = String(project.description || "");
  const badges: string[] = [];
  if (project.is_default) badges.push("default");
  if (project.is_system) badges.push("system");
  if (project.template_key) badges.push("template");
  return {
    id: project.id,
    name: project.name,
    badges,
    description: rawDescription.replace(/\s+/g, " ").trim(),
    descriptionTitle: rawDescription.trim(),
    isActive: Boolean(project.is_active),
    statusLabel: project.is_active ? "Active" : "Inactive",
    classLabel: classOf(project),
    members: countOf(project.member_count) ?? countOf(project.members_count),
    updatedAt: typeof project.updated_at === "string" && project.updated_at ? project.updated_at : null,
  };
}

/** Problems per Workspace id from one admin problems answer (both severities; acknowledged ones are already left out). */
export function problemCountsByWorkspace(
  problems: ReadonlyArray<{ severity: string; workspace: { id: string } | null }>,
): Record<string, { total: number; problem: number }> {
  const counts: Record<string, { total: number; problem: number }> = {};
  for (const item of problems) {
    const id = item.workspace?.id;
    if (!id) continue;
    const entry = (counts[id] ||= { total: 0, problem: 0 });
    entry.total += 1;
    if (item.severity === "problem") entry.problem += 1;
  }
  return counts;
}
