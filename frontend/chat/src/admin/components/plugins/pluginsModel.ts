import type {
  AvailablePlugin,
  AvailableViewer,
  ImageEntry,
  ImageOutcome,
  ImageReport,
  PluginConflict,
  PluginContribution,
  PluginInstall,
  PluginPermissions,
  PluginScope,
  PluginUi,
} from "./pluginsApi";

// The presentation model of the Plugins pages (plugins contract §6): a plugin of the image as a row with its switch,
// what it brings in words, how a refusal reads, and what the last start did with the image's folder. Pure, so the
// unit tests cover it without a browser.

import { listWords, plural, summaryText } from "./pluginWords";

// ---- a plugin of the image as a row ------------------------------------------------------------------------------

export type AvailableRow = {
  key: string;
  name: string;
  meta: string;
  description: string;
  lines: string[];
  // Missing from the image at the last start: greyed, never switchable.
  missing: boolean;
  // The switch, or only "On" / "Off" as text (members, greyed rows).
  switchable: boolean;
  on: boolean;
  // Opens the install's detail (contributions, settings, pages).
  canOpen: boolean;
  needsSettings: boolean;
};

export const MAX_SUMMARY_LINES = 5;

/** The row of one image plugin for the viewer of a Workspace's list. */
export function availableRow(item: AvailablePlugin, viewer: Pick<AvailableViewer, "can_activate"> | null): AvailableRow {
  const missing = !item.in_image;
  const on = item.active && !missing;
  return {
    key: item.plugin,
    name: item.name,
    meta: [item.version, item.publisher].filter(Boolean).join(" · "),
    description: item.description,
    lines: (item.summary ?? []).slice(0, MAX_SUMMARY_LINES).map(summaryText).filter(Boolean),
    missing,
    switchable: !missing && Boolean(viewer?.can_activate),
    on,
    canOpen: on && Boolean(item.install_id),
    needsSettings: on && item.needs_settings,
  };
}

/** The row after a switch call answered: on or off as the install says, and its install id. */
export function afterSwitch(item: AvailablePlugin, install: Pick<PluginInstall, "id" | "status">): AvailablePlugin {
  return { ...item, active: install.status === "active", install_id: install.id };
}

/** Admin › Plugins: in how many Workspaces the plugin is on now (`active_workspaces`, live). */
export function activeWorkspacesText(count: number | undefined): string {
  if (count === undefined) return "";
  return count ? `On in ${plural(count, "Workspace")}` : "Not on in any Workspace";
}

/** The empty list: how a plugin gets here (the folder only when the viewer may see it). */
export function emptyText(folder: string | null): string {
  const where = folder ? `the image's plugin folder (${folder})` : "the image's plugin folder";
  return `No plugins yet. An administrator adds a plugin by putting it into ${where}; it then appears here.`;
}

export function scopeText(scope: PluginScope): string {
  return scope === "platform" ? "Whole platform" : "This Workspace";
}

// ---- the detail of an install ------------------------------------------------------------------------------------

const KIND_WORDS: Record<PluginContribution["kind"], [string, string]> = {
  skill: ["skill", "skills"], workflow: ["workflow", "workflows"], role: ["role", "roles"],
  function: ["function", "functions"], mcp_server: ["MCP server", "MCP servers"],
};

export const kindLabel = (kind: PluginContribution["kind"]) => {
  const word = KIND_WORDS[kind][0];
  return word.charAt(0).toUpperCase() + word.slice(1);
};

/** A function by its name: one the plugin brings, else its key in words ("work_items" → "Work items"). */
export function functionLabel(key: string, permissions: Pick<PluginPermissions, "functions">): string {
  const brought = (permissions.functions ?? []).find((fn) => fn.key === key);
  if (brought) return brought.name;
  const words = key.replace(/[_-]+/g, " ").trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : key;
}

/** What a contribution is called: the name the package gave it (roles, functions, workflows), else its key. */
export function contributionName(item: Pick<PluginContribution, "kind" | "key">, permissions: PluginPermissions): string {
  if (item.kind === "role") return (permissions.roles ?? []).find((role) => role.key === item.key)?.name ?? item.key;
  if (item.kind === "function") return functionLabel(item.key, permissions);
  if (item.kind === "workflow") return (permissions.workflows ?? []).find((flow) => flow.key === item.key)?.name ?? item.key;
  return item.key;
}

const AREA_WORDS: Record<string, string> = { work: "Work", knowledge: "Knowledge", operations: "Operations", admin: "Admin",
  workspace: "Workspace overview", work_item: "Work item", run: "Run", repository: "Repository" };

/** The pages, tiles and tabs a plugin brings, as "Releases" + "Page in Work" lines (empty when it brings none). */
export function uiContents(ui: PluginUi | null | undefined): { title: string; where: string }[] {
  if (!ui) return [];
  const where = (slot: { where?: string | null }, kind: string) => {
    const area = slot.where ? AREA_WORDS[slot.where] ?? slot.where : "";
    return area ? `${kind} in ${area}` : kind;
  };
  return [
    ...(ui.pages ?? []).map((slot) => ({ title: slot.title, where: where(slot, "Page") })),
    ...(ui.tiles ?? []).map((slot) => ({ title: slot.title, where: where(slot, "Tile") })),
    ...(ui.tabs ?? []).map((slot) => ({ title: slot.title, where: where(slot, "Tab") })),
    ...(ui.phone ?? []).map((slot) => ({ title: slot.title, where: "Page on the phone" })),
  ];
}

// ---- refusals ----------------------------------------------------------------------------------------------------

const CONFLICT_TITLES: Record<string, string> = {
  plugin_already_installed: "Already installed here",
  skill_name_taken: "Skill name taken",
  plugin_version_differs: "Installed elsewhere in another version",
  workflow_key_taken: "Workflow already exists",
  role_key_taken: "Role already exists",
  function_key_taken: "Function already exists",
  role_function_unknown: "Role needs unknown functions",
  mcp_server_name_taken: "MCP server name taken",
  skill_draft_open: "Open draft of a skill",
};

/** A conflict in words: a short title and the server's sentence. */
export function conflictText(conflict: PluginConflict): { title: string; message: string } {
  return { title: CONFLICT_TITLES[conflict.code] ?? "Conflict", message: conflict.message };
}

/** 409 plugin_not_installable on switching on, in one sentence that names what is in the way. */
export function notInstallableText(conflicts: Pick<PluginConflict, "kind" | "key">[]): string {
  const named = conflicts.filter((item) => item.key).map((item) => `the ${(KIND_WORDS as Record<string, [string, string]>)[item.kind]?.[0] ?? "plugin"} ${item.key}`);
  return named.length
    ? `Not switched on: this Workspace already has ${listWords(named)}, which the plugin would bring too.`
    : "Not switched on: something the plugin brings already exists in this Workspace.";
}

const isRecord = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value);

export type PluginErrorView = { kind: "forbidden" | "message"; text: string };

/** A refusal from the plugin routes in words (contract §6); other errors keep the server's sentence. */
export function pluginErrorView(error: unknown): PluginErrorView {
  const value = isRecord(error) ? error : {};
  const detail = isRecord(value.detail) ? value.detail : {};
  const code = typeof value.code === "string" ? value.code : typeof detail.code === "string" ? detail.code : "";
  const status = typeof value.status === "number" ? value.status : 0;
  const message = typeof detail.message === "string" && detail.message
    ? detail.message
    : error instanceof Error && error.message ? error.message : "";
  if (code === "plugin_not_installable") {
    return { kind: "message", text: notInstallableText((Array.isArray(detail.conflicts) ? detail.conflicts : []).filter(isRecord) as PluginConflict[]) };
  }
  if (code === "plugin_not_available") return { kind: "message", text: "This plugin is no longer in the Octryx image." };
  if (code === "plugin_not_active") return { kind: "message", text: "This plugin was never switched on in this Workspace." };
  if (status === 403) return { kind: "forbidden", text: message || "Only a Workspace admin or owner switches plugins here." };
  return { kind: "message", text: message || "The request failed." };
}

// ---- the image folder's last start -------------------------------------------------------------------------------

const OUTCOME_WORDS: Record<ImageOutcome, string> = {
  available: "new and available",
  upgraded: "upgraded",
  unchanged: "unchanged",
  enabled: "back in the image and switched on again",
  disabled: "no longer in the image and switched off",
  failed: "failed",
};
const OUTCOME_ORDER: ImageOutcome[] = ["available", "upgraded", "enabled", "unchanged", "disabled", "failed"];

/** One outcome in words ("taken over from an earlier upload"); an unknown outcome keeps its word. */
export function outcomeText(outcome: string): string {
  return OUTCOME_WORDS[outcome as ImageOutcome] ?? outcome.replace(/_/g, " ");
}

const RULES: Record<string, string> = {
  script: "Executable script",
  shell_injection: "Shell command in the text",
  execution_frontmatter: "Execution settings in the frontmatter",
  network: "Network access",
  changing_command: "Command that changes systems",
  secret: "Secret in the files",
  mcp_local_process: "Local MCP process",
  mcp_image_tag: "MCP image without digest",
  mcp_credential_passthrough: "MCP credential passed through",
  mcp_outbound: "MCP outbound connection",
};

const ruleText = (rule: string) => RULES[rule] ?? (rule ? rule.charAt(0).toUpperCase() + rule.slice(1).replace(/_/g, " ") : "Finding");

const IMAGE_CODES: Record<string, string> = {
  plugin_package_invalid: "The package is not valid",
  plugin_duplicate_in_image: "The plugin is in the folder more than once",
  plugin_not_installable: "It conflicts with what is installed",
  plugin_installed_by_hand: "It is installed for the platform by upload",
  plugin_install_failed: "The install failed",
};

export type ImageFailure = { key: string; title: string; detail: string; reason: string; message: string; items: string[] };
export type ImageReportView = {
  folder: string; started: string | null; counts: string; failed: ImageFailure[];
  // What to say instead of counts: no folder in the image, or an empty folder; null when there are entries.
  emptyText: string | null;
};

function failureItems(entry: ImageEntry): string[] {
  return [
    ...(entry.issues ?? []).map((issue) => (issue.path ? `${issue.message} (${issue.path})` : issue.message)),
    ...(entry.conflicts ?? []).map((conflict) => {
      const text = conflictText(conflict);
      return `${text.title}: ${text.message}`;
    }),
    ...(entry.blocking_findings ?? []).map((finding) => `${finding.skill ? `Skill ${finding.skill}: ` : ""}${ruleText(finding.rule)}. ${finding.message}`),
  ];
}

/** The image folder's last start in words: counts per outcome, and every failed entry with its reason. */
export function imageReportView(report: ImageReport): ImageReportView {
  const entries = report.entries ?? [];
  const known = new Set<string>(OUTCOME_ORDER);
  const order = [...OUTCOME_ORDER, ...new Set(entries.map((entry) => entry.outcome).filter((outcome) => !known.has(outcome)))];
  const counts = order.map((outcome) => ({ outcome, n: entries.filter((entry) => entry.outcome === outcome).length }))
    .filter((item) => item.n > 0)
    .map((item) => `${plural(item.n, "plugin")} ${outcomeText(item.outcome)}`)
    .join(" · ");
  const same = (a: string, b: string) => a.replace(/\.$/, "").trim().toLowerCase() === b.replace(/\.$/, "").trim().toLowerCase();
  const failed = entries.filter((entry) => entry.outcome === "failed").map((entry, index) => {
    const reason = (entry.code && IMAGE_CODES[entry.code]) || "The install failed";
    return {
      key: `${entry.entry}-${index}`,
      title: entry.entry,
      detail: [entry.plugin, entry.version].filter(Boolean).join(" "),
      reason,
      // The sentence, unless it only repeats the reason.
      message: same(entry.message ?? "", reason) ? "" : entry.message ?? "",
      items: failureItems(entry),
    };
  });
  const emptyText = entries.length ? null
    : report.folder_exists === false ? "No plugin folder in this image; nothing was changed." : "No plugins found in the folder.";
  return { folder: report.folder, started: report.started_at ?? null, counts, emptyText, failed };
}
