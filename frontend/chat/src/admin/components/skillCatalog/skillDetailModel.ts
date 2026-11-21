import { refusalText, shortCommit } from "./skillCatalogModel";
import type { FileEntry, Finding, SkillDetail, SkillVersion, Surface, UpstreamStatus } from "./skillCatalogTypes";
import type { Readiness, SurfaceReach, WorkspaceReach } from "./skillDeliveryTypes";

// The skill detail page model (mock `renderDetail` and helpers): which version the page shows, finding
// groups, the delivered plugin layout, upstream check sentences and the Workspace reach summary. Pure functions only
// (unit-tested in tests/unit/skillDetailModel.test.mjs).

/** The version the page works on: the open draft or review, else the published one, else the newest. */
export function workingVersion(detail: Pick<SkillDetail, "open" | "published" | "versions">): SkillVersion | null {
  return detail.open ?? detail.published ?? detail.versions[0] ?? null;
}

/** The owner's display name from the version authors (the detail carries only `owner_id`). */
export function ownerName(detail: Pick<SkillDetail, "owner_id" | "versions">): string {
  if (!detail.owner_id) return "—";
  return detail.versions.find((row) => row.created_by === detail.owner_id)?.author_name ?? detail.owner_id.slice(0, 8);
}

export function descriptionOf(version: SkillVersion | null): string {
  const value = version?.frontmatter?.description;
  return typeof value === "string" ? value : "";
}

export const SEVERITIES: Finding["severity"][] = ["high", "medium", "info"];
export const SEVERITY_LABELS: Record<Finding["severity"], string> = { high: "High", medium: "Medium", info: "Info" };
/** Check-row icon and tone class per severity (mock `checkRows`: er ✕, wa !, in i). */
export const SEVERITY_MARK: Record<Finding["severity"], { icon: string; tone: string }> = {
  high: { icon: "✕", tone: "skills__er" },
  medium: { icon: "!", tone: "skills__wa" },
  info: { icon: "i", tone: "skills__in" },
};

export function findingsBySeverity(findings: Finding[]): { severity: Finding["severity"]; findings: Finding[] }[] {
  return SEVERITIES.map((severity) => ({ severity, findings: findings.filter((item) => item.severity === severity) }))
    .filter((group) => group.findings.length > 0);
}

export function findingPlace(finding: Pick<Finding, "file" | "line">): string {
  if (!finding.file) return "";
  return finding.line ? `${finding.file}:${finding.line}` : finding.file;
}

export function toggleId(ids: string[], id: string, on: boolean): string[] {
  const rest = ids.filter((item) => item !== id);
  return on ? [...rest, id] : rest;
}

export function sameIds(a: string[], b: string[]): boolean {
  return a.length === b.length && [...a].sort().join("\n") === [...b].sort().join("\n");
}

export function scriptFiles(files: FileEntry[]): FileEntry[] {
  return files.filter((file) => file.kind === "script");
}

export function referenceFiles(files: FileEntry[]): FileEntry[] {
  return files.filter((file) => file.kind === "reference");
}

const FILE_KINDS: Record<string, string> = {
  instructions: "Instructions", reference: "Reference", asset: "Asset", script: "Script", licence: "Licence",
};

export function fileKindLabel(file: Pick<FileEntry, "kind">, scriptsAllowed: boolean): string {
  if (file.kind === "script") return scriptsAllowed ? "Script · delivered" : "Script · withheld";
  return FILE_KINDS[file.kind] ?? file.kind;
}

/** Tags typed as text: commas or spaces separate them; empty entries dropped, order kept, duplicates removed. */
export function parseTags(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).map((tag) => tag.trim().replace(/^#/, "")).filter(Boolean))];
}

/** "YYYY-MM-DD HH:MM" of a server timestamp (display only). */
export function formatWhen(value: string | null | undefined): string {
  return value ? value.slice(0, 16).replace("T", " ") : "—";
}

/** The result line of "Check for updates". */
export function checkSentence(status: UpstreamStatus): { text: string; tone: "ok" | "update" | "error" } {
  if (status.error) return { text: `Check failed: ${refusalText({ code: status.error })}`, tone: "error" };
  if (status.update_available) {
    const moved = status.path_moved ? ", skill folder moved" : "";
    return { text: `Update available: ${shortCommit(status.current_commit)} → ${shortCommit(status.latest_commit)}${moved}.`, tone: "update" };
  }
  return { text: `Up to date with ${status.compare_ref || "upstream"} at ${shortCommit(status.latest_commit)}.`, tone: "ok" };
}

/** The per-session plugin folder an octryx-claude session receives for this one skill (Delivery tab). */
export function pluginLayout(plugin: string, name: string, files: { path: string }[]): string {
  const lines = [`<launcher home>/skill-plugins/<session>/${plugin}/`, "├── .claude-plugin/plugin.json", "└── skills/", `    └── ${name}/`];
  files.forEach((file, index) => lines.push(`        ${index === files.length - 1 ? "└──" : "├──"} ${file.path}`));
  return lines.join("\n");
}

const READINESS_RANK: Record<string, number> = { ready: 0, restricted: 1, needs_mcp_policy: 2 };

/** One Workspace row: the delivered surfaces' assignment and the least ready readiness. */
export function reachSummary(row: WorkspaceReach): { delivered: boolean; assignedBy: string; readiness: Readiness | null } {
  const entries = Object.values(row.surfaces).filter((entry): entry is SurfaceReach => Boolean(entry));
  const delivered = entries.filter((entry) => entry.delivered);
  const pick = delivered[0] ?? entries[0];
  const readiness = delivered
    .map((entry) => entry.readiness)
    .filter((value): value is Readiness => Boolean(value))
    .sort((a, b) => (READINESS_RANK[b.state] ?? 1) - (READINESS_RANK[a.state] ?? 1))[0] ?? null;
  return { delivered: delivered.length > 0, assignedBy: pick?.assigned_by ?? "", readiness };
}

export function surfaceFlag(version: SkillVersion | null, surface: Surface): boolean {
  if (!version) return false;
  return surface === "platform_chat" ? version.available_platform_chat : version.available_octryx_claude;
}
