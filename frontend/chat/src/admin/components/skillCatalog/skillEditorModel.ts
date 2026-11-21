// The skill editor model: the form state of one skill draft, the create / draft-save bodies, the live spec
// checks and the SKILL.md preview text. Pure functions only (unit-tested in tests/unit/skillEditorModel.test.mjs).
// The server is the parser and validator of record; these checks only mirror its rules for instant feedback.

import { descriptionIssue, nameIssue } from "./skillCatalogModel";
import type { Extension, SkillVersion, Surface } from "./skillCatalogTypes";

export const DESCRIPTION_MAX = 1024;
export const WHEN_TO_USE_MAX = 1024;
export const SKILL_MD_LINE_WARNING = 500;
/** Frontmatter keys that grant tools, run hooks or change the execution context; never delivered (spec.py). */
export const EXECUTION_KEYS = ["allowed-tools", "disallowed-tools", "hooks", "model", "effort", "context", "agent", "background", "shell"];

/** The editor's left section nav (anchor ids of the form sections). */
export const EDITOR_SECTIONS = [
  { id: "skill-editor-spec", label: "Agent Skills fields" },
  { id: "skill-editor-body", label: "Instructions" },
  { id: "skill-editor-extension", label: "Octryx fields" },
  { id: "skill-editor-availability", label: "Availability" },
] as const;

export type ToolLists = { required: string; optional: string };
export type EditorForm = {
  name: string;
  description: string;
  whenToUse: string;
  categoryId: string;
  tags: string;
  body: string;
  tools: Record<Surface, ToolLists>;
  roles: string;
  /** One `key: value` per line (extension.output_contract is a string map). */
  outputContract: string;
  /** One rule per line. */
  safetyRules: string;
  availablePlatformChat: boolean;
  availableOctryxClaude: boolean;
  note: string;
};
/** What the editor started from: the loaded frontmatter and extension are kept, the form only overwrites its fields. */
export type EditorBase = { frontmatter: Record<string, unknown>; extension: Extension };

export type CheckTone = "ok" | "wa" | "er" | "in";
export type EditorCheck = { id: string; tone: CheckTone; text: string };

export function emptyForm(): EditorForm {
  return {
    name: "", description: "", whenToUse: "", categoryId: "", tags: "", body: "",
    tools: { platform_chat: { required: "", optional: "" }, octryx_claude: { required: "", optional: "" } },
    roles: "", outputContract: "", safetyRules: "", availablePlatformChat: true, availableOctryxClaude: true, note: "",
  };
}

const text = (value: unknown) => (typeof value === "string" ? value : "");
const strings = (value: unknown) => (Array.isArray(value) ? value.map((item) => String(item ?? "")).filter(Boolean) : []);

/** Comma- or newline-separated values, trimmed and de-duplicated in input order. */
export function splitList(value: string): string[] {
  const seen: string[] = [];
  for (const part of value.split(/[,\n]/)) {
    const item = part.trim();
    if (item && !seen.includes(item)) seen.push(item);
  }
  return seen;
}

/** One entry per non-empty line (tool patterns may contain commas, e.g. `Bash(git log *, …)`, so lines only). */
export function splitLines(value: string): string[] {
  const seen: string[] = [];
  for (const line of value.split(/\r?\n/)) {
    const item = line.trim();
    if (item && !seen.includes(item)) seen.push(item);
  }
  return seen;
}

export function parseContract(value: string): Record<string, string> {
  const contract: Record<string, string> = {};
  for (const line of value.split(/\r?\n/)) {
    const at = line.indexOf(":");
    if (at <= 0) continue;
    const key = line.slice(0, at).trim();
    const entry = line.slice(at + 1).trim();
    if (key && entry) contract[key] = entry;
  }
  return contract;
}

export function contractText(value: unknown): string {
  if (!value || typeof value !== "object" || Array.isArray(value)) return "";
  return Object.entries(value as Record<string, unknown>).map(([key, entry]) => `${key}: ${String(entry ?? "")}`).join("\n");
}

/** Lines of the contract text that are not `key: value` (they would be dropped on save). */
export function contractProblems(value: string): string[] {
  return value.split(/\r?\n/).map((line) => line.trim()).filter((line) => line && !/^[^:]+:\s*\S/.test(line));
}

export function formFromVersion(version: SkillVersion, tags: string[]): { form: EditorForm; base: EditorBase } {
  const frontmatter = { ...(version.frontmatter ?? {}) };
  const extension: Extension = { ...(version.extension ?? {}) };
  const tools = (extension.tools ?? {}) as Partial<Record<Surface, { required?: unknown; optional?: unknown }>>;
  const lists = (surface: Surface): ToolLists => ({
    required: strings(tools[surface]?.required).join("\n"),
    optional: strings(tools[surface]?.optional).join("\n"),
  });
  return {
    base: { frontmatter, extension },
    form: {
      name: text(frontmatter.name),
      description: text(frontmatter.description),
      whenToUse: text(frontmatter.when_to_use),
      categoryId: version.category_id ?? "",
      tags: tags.join(", "),
      body: version.body ?? "",
      tools: { platform_chat: lists("platform_chat"), octryx_claude: lists("octryx_claude") },
      roles: strings(extension.allowed_roles).join(", "),
      outputContract: contractText(extension.output_contract),
      safetyRules: strings(extension.safety_rules).join("\n"),
      availablePlatformChat: version.available_platform_chat,
      availableOctryxClaude: version.available_octryx_claude,
      note: version.note ?? "",
    },
  };
}

/** The loaded frontmatter with only the edited fields overwritten (unknown upstream keys such as `metadata` stay). */
export function buildFrontmatter(form: EditorForm, base: EditorBase | null): Record<string, unknown> {
  const frontmatter: Record<string, unknown> = { ...(base?.frontmatter ?? {}) };
  if (!base) frontmatter.name = form.name.trim();
  frontmatter.description = form.description.trim();
  if (form.whenToUse.trim()) frontmatter.when_to_use = form.whenToUse.trim();
  else delete frontmatter.when_to_use;
  return frontmatter;
}

export function buildExtension(form: EditorForm, base: EditorBase | null): Extension {
  const tools = (surface: Surface) => ({ required: splitLines(form.tools[surface].required), optional: splitLines(form.tools[surface].optional) });
  return {
    ...(base?.extension ?? {}),
    tools: { platform_chat: tools("platform_chat"), octryx_claude: tools("octryx_claude") },
    output_contract: parseContract(form.outputContract),
    safety_rules: splitLines(form.safetyRules),
    allowed_roles: splitList(form.roles.toLowerCase()),
  };
}

export function tagList(form: EditorForm): string[] {
  return splitList(form.tags.toLowerCase());
}

/** `POST /skills` body of a new skill (licence defaults to Internal on the server). */
export function createBody(form: EditorForm) {
  return {
    name: form.name.trim(),
    category_id: form.categoryId,
    frontmatter: buildFrontmatter(form, null),
    body: form.body,
    extension: buildExtension(form, null),
    tags: tagList(form),
    available_platform_chat: form.availablePlatformChat,
    available_octryx_claude: form.availableOctryxClaude,
    ...(form.note.trim() ? { note: form.note.trim() } : {}),
  };
}

/** `PUT /skills/{id}/versions/{v}` body of an existing draft. */
export function saveBody(form: EditorForm, base: EditorBase) {
  return {
    frontmatter: buildFrontmatter(form, base),
    body: form.body,
    extension: buildExtension(form, base),
    category_id: form.categoryId,
    available_platform_chat: form.availablePlatformChat,
    available_octryx_claude: form.availableOctryxClaude,
    note: form.note.trim() || null,
  };
}

function yamlValue(value: unknown): string {
  if (typeof value === "string") return value.replace(/\r?\n/g, " ");
  return JSON.stringify(value);
}

/** The SKILL.md text the save would produce, for the display-only preview (the server renders the real file). */
export function skillMdText(frontmatter: Record<string, unknown>, body: string): string {
  const ordered = ["name", "description", ...Object.keys(frontmatter).filter((key) => key !== "name" && key !== "description")];
  const lines = ordered.filter((key) => key in frontmatter).map((key) => `${key}: ${yamlValue(frontmatter[key])}`);
  return `---\n${lines.join("\n")}\n---\n\n${body}`;
}

export function lineCount(value: string): number {
  return value.split(/\r?\n/).length;
}

/** Shell injection blocks (`!`cmd`` or a ```! fence) are never delivered. */
export function hasShellBlock(body: string): boolean {
  return /!`|```!/.test(body);
}

export function strippedKeys(frontmatter: Record<string, unknown>): string[] {
  return EXECUTION_KEYS.filter((key) => key in frontmatter);
}

/** Problems that make a save pointless (the server would refuse); `isNew` adds the name rule. */
export function blockingIssues(form: EditorForm, isNew: boolean): string[] {
  const issues: string[] = [];
  const name = isNew ? nameIssue(form.name.trim()) : null;
  if (name) issues.push(name);
  const description = descriptionIssue(form.description);
  if (description) issues.push(description);
  if (form.whenToUse.length > WHEN_TO_USE_MAX) issues.push(`When to use: at most ${WHEN_TO_USE_MAX} characters.`);
  if (!form.categoryId) issues.push("Choose a category.");
  return issues;
}

export function editorChecks(form: EditorForm, base: EditorBase | null): EditorCheck[] {
  const name = form.name.trim();
  const nameProblem = nameIssue(name);
  const description = form.description;
  const descriptionProblem = descriptionIssue(description);
  const frontmatter = buildFrontmatter(form, base);
  const lines = lineCount(skillMdText(frontmatter, form.body));
  const rules = splitLines(form.safetyRules).length;
  const stripped = strippedKeys(frontmatter);
  const checks: EditorCheck[] = [
    nameProblem
      ? { id: "name", tone: "er", text: `Name: ${nameProblem}` }
      : { id: "name", tone: "ok", text: "Name: lower-case letters, digits and single hyphens, at most 64" },
    descriptionProblem
      ? { id: "description", tone: "er", text: `Description ${description.length} / ${DESCRIPTION_MAX}: ${descriptionProblem}` }
      : { id: "description", tone: "ok", text: `Description ${description.length} / ${DESCRIPTION_MAX}` },
    lines <= SKILL_MD_LINE_WARNING
      ? { id: "lines", tone: "ok", text: `SKILL.md ${lines} lines (under ${SKILL_MD_LINE_WARNING})` }
      : { id: "lines", tone: "wa", text: `SKILL.md ${lines} lines: recommended under ${SKILL_MD_LINE_WARNING}; move details into references/` },
    form.categoryId
      ? { id: "category", tone: "ok", text: "Category chosen" }
      : { id: "category", tone: "er", text: "Choose a category" },
    hasShellBlock(form.body)
      ? { id: "shell", tone: "er", text: "Shell injection block found: it is not delivered" }
      : { id: "shell", tone: "ok", text: "No shell injection blocks" },
    rules
      ? { id: "safety", tone: "ok", text: `${rules} safety rule${rules === 1 ? "" : "s"}, appended to the instructions on both surfaces` }
      : { id: "safety", tone: "in", text: "No safety rules" },
    stripped.length
      ? { id: "stripped", tone: "wa", text: `Permission keys in the frontmatter are stripped on delivery: ${stripped.join(", ")}` }
      : { id: "stripped", tone: "in", text: "Permission keys (allowed-tools, hooks, model, …) are stripped on delivery" },
    { id: "review", tone: "in", text: "Saving runs the security review and the Agent Skills spec check; the draft is published after approval (Settings → Governance → Approval rule)." },
  ];
  if (form.whenToUse.length > WHEN_TO_USE_MAX) {
    checks.splice(2, 0, { id: "when", tone: "er", text: `When to use ${form.whenToUse.length} / ${WHEN_TO_USE_MAX}` });
  }
  return checks;
}

export const CHECK_ICONS: Record<CheckTone, string> = { ok: "✓", wa: "!", er: "✕", in: "i" };
