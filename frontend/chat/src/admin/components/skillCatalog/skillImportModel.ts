// The skill import model: what an inspection offers (importable, already in the catalog, refused), the
// `POST /import/git` body built from the inspected commit, and the ids an import created. Pure functions only.

import type { InspectItem, InspectResult } from "./skillDeliveryTypes";

export type ImportMode = "upload" | "git" | "market";
export type TrackingMode = "pinned" | "follow";
export type Trust = "official" | "community" | "internal";

export const UPLOAD_MAX_BYTES = 5 * 1024 * 1024;
const COMMIT = /^[0-9a-f]{40}$/;

export function itemKey(item: Pick<InspectItem, "kind" | "path" | "name">): string {
  return `${item.kind}:${item.path}:${item.name}`;
}

export type ItemOffer = { importable: boolean; reason: string | null };

/** Whether an inspected item can be imported as a new entry, and why not. */
export function itemOffer(item: InspectItem): ItemOffer {
  if (item.existing?.relation === "update") return { importable: false, reason: "Already in the catalog: use its update." };
  if (item.existing?.relation === "name_taken") return { importable: false, reason: "A skill with this name already exists." };
  if (item.problem) return { importable: false, reason: problemText(item.problem) };
  if (!item.importable) {
    const errors = (item.spec_issues ?? []).some((issue) => issue.severity === "error");
    return { importable: false, reason: errors ? "Does not follow the Agent Skills spec (see the issues)." : "Not importable." };
  }
  return { importable: true, reason: null };
}

function problemText(problem: unknown): string {
  if (typeof problem === "string") return problem;
  if (problem && typeof problem === "object") {
    const value = problem as Record<string, unknown>;
    if (typeof value.message === "string") return value.message;
    if (typeof value.code === "string") return value.code.replace(/_/g, " ");
  }
  return "Not importable.";
}

export function inspectedItems(result: InspectResult | null): InspectItem[] {
  return result ? [...result.skills, ...result.mcp_servers] : [];
}

/** Every item that can be imported starts selected. */
export function defaultSelection(result: InspectResult | null): string[] {
  return inspectedItems(result).filter((item) => itemOffer(item).importable).map(itemKey);
}

/** Following upstream needs a branch or tag; a commit (or the default HEAD) can only be pinned. */
export function canFollow(ref: string | null | undefined): boolean {
  const value = (ref ?? "").trim();
  return Boolean(value) && value !== "HEAD" && !COMMIT.test(value);
}

/** The commit an import must name: the marketplace commit for a marketplace entry, else the inspected commit. */
export function importCommit(result: InspectResult): string {
  const marketCommit = result.plugin && typeof result.plugin.marketplace_commit === "string" ? result.plugin.marketplace_commit : "";
  return marketCommit || result.commit;
}

export type GitRequest = { url: string; ref: string; path: string; marketplacePlugin: string };
export type GitImportOptions = { categoryId: string; tracking: TrackingMode; trust: Trust | ""; tags: string[] };

/** `POST /import/git`: the request the inspection was made with, at the inspected commit, for the selected items. */
export function gitImportBody(request: GitRequest, result: InspectResult, selected: string[], options: GitImportOptions) {
  const chosen = inspectedItems(result).filter((item) => selected.includes(itemKey(item)) && itemOffer(item).importable);
  const tracking = options.tracking === "follow" && canFollow(result.ref) ? "follow" : "pinned";
  return {
    url: request.url.trim(),
    ...(request.ref.trim() ? { ref: request.ref.trim() } : {}),
    ...(request.path.trim() ? { path: request.path.trim() } : {}),
    ...(request.marketplacePlugin.trim() ? { marketplace_plugin: request.marketplacePlugin.trim() } : {}),
    commit: importCommit(result),
    ...(options.trust ? { trust: options.trust } : {}),
    items: chosen.map((item) => ({
      kind: item.kind, path: item.path, name: item.name, category_id: options.categoryId, tracking_mode: tracking, tags: options.tags,
    })),
  };
}

export function inspectBody(request: GitRequest, mode: ImportMode) {
  return {
    url: request.url.trim(),
    ...(request.ref.trim() ? { ref: request.ref.trim() } : {}),
    ...(mode === "git" && request.path.trim() ? { path: request.path.trim() } : {}),
    ...(mode === "market" ? { marketplace_plugin: request.marketplacePlugin.trim() } : {}),
  };
}

/** Skill ids from an import response: `{imported: [{skill_id}]}` (Git) or one `{skill_id}` (upload). */
export function importedIds(response: unknown): string[] {
  if (!response || typeof response !== "object") return [];
  const value = response as { imported?: unknown; skill_id?: unknown };
  if (Array.isArray(value.imported)) {
    return value.imported
      .map((entry) => (entry && typeof entry === "object" ? (entry as { skill_id?: unknown }).skill_id : null))
      .filter((id): id is string => typeof id === "string" && Boolean(id));
  }
  return typeof value.skill_id === "string" ? [value.skill_id] : [];
}

/** A local refusal before the upload is sent (the server checks again). */
export function uploadIssue(file: { name: string; size: number } | null): string | null {
  if (!file) return "Choose a SKILL.md or a .zip file.";
  if (!/\.(md|zip)$/i.test(file.name)) return "Upload a .md or a .zip file.";
  if (file.size > UPLOAD_MAX_BYTES) return "The file is above 5 MB.";
  return null;
}

export function splitTags(value: string): string[] {
  const seen: string[] = [];
  for (const part of value.split(",")) {
    const tag = part.trim().toLowerCase();
    if (tag && !seen.includes(tag)) seen.push(tag);
  }
  return seen;
}

export function selectedItems(result: InspectResult | null, selected: string[]): InspectItem[] {
  return inspectedItems(result).filter((item) => selected.includes(itemKey(item)) && itemOffer(item).importable);
}

/** The primary action of the inspect step, e.g. "Import 2 skills and 1 MCP server entry as drafts". */
export function importLabel(items: Pick<InspectItem, "kind">[]): string {
  const skills = items.filter((item) => item.kind === "skill").length;
  const servers = items.length - skills;
  if (!items.length) return "Import";
  const parts = [
    skills ? `${skills} skill${skills === 1 ? "" : "s"}` : "",
    servers ? `${servers} MCP server entr${servers === 1 ? "y" : "ies"}` : "",
  ].filter(Boolean);
  return `Import ${parts.join(" and ")} as draft${items.length === 1 ? "" : "s"}`;
}

export type PreviewTone = "ok" | "wa" | "er" | "in";
export type PreviewLine = { id: string; tone: PreviewTone; text: string };

/** The security review preview of the selected items (the full review runs on import). */
export function securityPreview(items: InspectItem[]): PreviewLine[] {
  const lines: PreviewLine[] = [];
  for (const item of items) {
    for (const script of item.scripts ?? []) {
      lines.push({ id: `script:${item.name}:${script}`, tone: "wa", text: `${item.name}/${script} is a script: withheld unless a platform admin allows it for that version.` });
    }
    if (item.execution_keys?.length) {
      lines.push({ id: `keys:${item.name}`, tone: "in", text: `${item.name}: ${item.execution_keys.join(", ")} in the frontmatter are stripped on delivery.` });
    }
    if (!item.licence.allowed) {
      lines.push({ id: `licence:${item.name}`, tone: "er", text: `${item.name}: licence ${item.licence.spdx ?? "unknown"} is not on the instance allow-list; it cannot be published.` });
    }
    for (const issue of (item.spec_issues ?? []).filter((entry) => entry.severity === "warning")) {
      lines.push({ id: `spec:${item.name}:${issue.code}`, tone: "wa", text: `${item.name}: ${issue.message}` });
    }
    if (item.kind === "mcp_server") {
      for (const name of item.launch_spec?.passthrough ?? []) {
        lines.push({ id: `pass:${item.name}:${name}`, tone: "er", text: `${name} would be copied from the user's environment: never passed through; supply it through a named connection or leave it unset.` });
      }
      if (item.launch_spec?.image && !item.launch_spec.image_digest) {
        lines.push({ id: `image:${item.name}`, tone: "wa", text: `${item.name} starts a local container pinned by tag only; the image digest is recorded at review.` });
      }
      lines.push({ id: `mcp:${item.name}`, tone: "in", text: `${item.name} is imported as an MCP server entry, not a skill. It runs only in Workspaces whose MCP policy allows it.` });
    }
  }
  const skills = items.filter((item) => item.kind === "skill");
  if (skills.length && !skills.some((item) => item.execution_keys?.length || item.scripts?.length)) {
    lines.push({ id: "clean", tone: "ok", text: `No scripts and no permission-widening frontmatter in the ${skills.length} selected skill${skills.length === 1 ? "" : "s"}.` });
  }
  return lines;
}
