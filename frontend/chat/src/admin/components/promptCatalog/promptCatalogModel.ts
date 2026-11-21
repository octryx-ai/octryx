// Pure helpers of the prompt catalog tab: grouping, placeholder preview, diff lines, refusal text.
import { RegistryApiError } from "../governedRegistry/registryApi";
import { describeRefusal, type Refusal } from "../governedRegistry/registryRefusals";
import type {
  PromptListItem,
  PromptScopeType,
  PromptTemplateView,
  PromptVersion,
  PromptWritableScope,
} from "./promptCatalogTypes";

export function groupByArea(items: PromptListItem[]): Array<{ area: string; items: PromptListItem[] }> {
  const groups = new Map<string, PromptListItem[]>();
  for (const item of items) {
    groups.set(item.area, [...(groups.get(item.area) ?? []), item]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([area, rows]) => ({ area, items: [...rows].sort((a, b) => a.key.localeCompare(b.key)) }));
}

// Same shape as the server's placeholder pattern (services/prompt_catalog/contract.py).
const PLACEHOLDER = /\{([A-Za-z_][A-Za-z0-9_]*)\}/g;

export function placeholderPreview(body: string, allowed: string[]): { used: string[]; unknown: string[] } {
  const used = Array.from(new Set(Array.from(body.matchAll(PLACEHOLDER), (match) => match[1])));
  return { used, unknown: used.filter((name) => !allowed.includes(name)) };
}

export type DiffLineKind = "added" | "removed" | "hunk" | "header" | "context";

export function diffLines(diff: string): Array<{ kind: DiffLineKind; text: string }> {
  if (!diff) return [];
  return diff
    .replace(/\n$/, "")
    .split("\n")
    .map((text) => {
      if (text.startsWith("+++") || text.startsWith("---")) return { kind: "header" as const, text };
      if (text.startsWith("@@")) return { kind: "hunk" as const, text };
      if (text.startsWith("+")) return { kind: "added" as const, text };
      if (text.startsWith("-")) return { kind: "removed" as const, text };
      return { kind: "context" as const, text };
    });
}

export const SCOPE_LABEL: Record<PromptScopeType, string> = {
  global: "Global",
  workflow: "Workflow",
  workspace: "Workspace",
};

export function scopeLabel(template: Pick<PromptTemplateView, "scope_type" | "scope_id">, names?: Map<string, string>) {
  if (template.scope_type === "global" || !template.scope_id) return SCOPE_LABEL.global;
  // Names are keyed by scope key ("workspace:<id>", scopeNames) or by id.
  const name = names?.get(`${template.scope_type}:${template.scope_id}`) ?? names?.get(template.scope_id);
  return `${SCOPE_LABEL[template.scope_type]} · ${name ?? template.scope_id}`;
}

export function publishedVersion(template: PromptTemplateView | undefined): PromptVersion | undefined {
  return template?.versions.find((item) => item.state === "published");
}

const TEXT: Record<string, string> = {
  prompt_key_not_found: "This prompt key is not registered in the catalog.",
  prompt_version_not_found: "This version does not exist.",
  prompt_version_not_draft: "Only a draft can be submitted for review; this version is no longer a draft.",
  prompt_version_retired: "This version is already retired.",
  prompt_review_required: "Every System prompt text needs a four-eyes review: submit the draft before publishing.",
  prompt_already_shipped: "This text already is the shipped text.",
  prompt_scope_not_found: "The Workspace or agent definition of this scope does not exist.",
  prompt_scope_forbidden: "You may not write texts for this scope: global texts need a platform admin, Workspace texts an owner or admin of that Workspace, workflow texts the workflow's creator or an admin.",
  prompt_workflow_not_found: "No workflow with this key exists, so it cannot have its own texts.",
  prompt_scope_invalid: "The scope is invalid: global takes no id, a workflow or Workspace needs one.",
  governance_approval_required: "Publishing needs an approved four-eyes approval for exactly this version.",
  self_approval_not_allowed: "The approval rule does not allow approving your own change: another person who may change this scope approves it.",
  http_403: "You may not see or change these texts. Ask a platform admin, or an owner of your Workspace or workflow.",
};

// prompt_scope_forbidden carries the scope it refused: say who may write there.
const FORBIDDEN_TEXT: Record<string, string> = {
  global: "Only a platform admin may change the global text. Write it for your Workspace or workflow instead.",
  workspace: "Only an owner or admin of this Workspace may change its texts.",
  workflow: "Only the workflow's creator or a platform admin may change its texts.",
};

const REASON_TEXT: Record<string, string> = {
  placeholder_unknown: "The body uses placeholders this key does not declare",
  placeholder_unbound: "The body uses a placeholder the call site does not supply",
  body_empty: "The body is empty",
  body_too_long: "The body is longer than the catalog allows",
  unknown_key: "The key is not registered",
};

export type PromptRefusal = Refusal & { names: string[] };

export function describePromptRefusal(error: unknown): PromptRefusal {
  const base = describeRefusal(error);
  const facts = error instanceof RegistryApiError ? error.facts : {};
  const names = Array.isArray(facts.names) ? facts.names.map(String) : [];
  if (base.code === "prompt_template_unavailable") {
    const reason = String(facts.reason ?? "");
    const text = REASON_TEXT[reason] ?? `The template was refused (${reason || "no reason"})`;
    return { code: base.code, text: names.length ? `${text}: ${names.join(", ")}.` : `${text}.`, names };
  }
  if (base.code === "prompt_scope_forbidden") {
    const text = FORBIDDEN_TEXT[String(facts.scope_type ?? "")] ?? TEXT.prompt_scope_forbidden;
    return { ...base, text, names };
  }
  return { ...base, text: TEXT[base.code] ?? base.text, names };
}

// A key is overridden when its published global version is not the shipped (seed) text.
export function isOverridden(item: Pick<PromptListItem, "published" | "seed_digest">): boolean {
  return Boolean(item.published && (item.published.source !== "seed" || item.published.digest !== item.seed_digest));
}

// --- Scopes (run texts) ---------------------------------------------------------------------------

export type ScopeRef = { scope_type: PromptScopeType; scope_id: string | null };

export const GLOBAL_SCOPE: ScopeRef = { scope_type: "global", scope_id: null };

export function scopeKey(scope: ScopeRef): string {
  return scope.scope_type === "global" || !scope.scope_id ? "global" : `${scope.scope_type}:${scope.scope_id}`;
}

// "workflow:epic-delivery" / "workspace:<id>" / "global" (the ?scope= link of the workflow editor).
export function parseScopeKey(value: string | null | undefined): ScopeRef | null {
  if (!value) return null;
  if (value === "global") return GLOBAL_SCOPE;
  const at = value.indexOf(":");
  const type = value.slice(0, at);
  const id = value.slice(at + 1);
  if (at < 1 || !id || !(type === "workflow" || type === "workspace")) return null;
  return { scope_type: type, scope_id: id };
}

// The scopes a run can be in, most specific first.
const PRECEDENCE: PromptScopeType[] = ["workspace", "workflow", "global"];

// What a run in `context` gets: the published text of the most specific scope that has one, else the shipped text.
// Same order as the server's resolver (global < workflow < workspace).
export function effectiveText(
  templates: PromptTemplateView[],
  seed: string,
  context: Partial<Record<PromptScopeType, string | null>>,
): { body: string; scope: ScopeRef | null; version: PromptVersion | null } {
  for (const type of PRECEDENCE) {
    const id = type === "global" ? null : context[type];
    if (type !== "global" && !id) continue;
    const template = templates.find((item) => item.scope_type === type && (type === "global" || item.scope_id === id));
    const version = publishedVersion(template);
    if (version) return { body: version.body ?? "", scope: { scope_type: type, scope_id: id ?? null }, version };
  }
  return { body: seed, scope: null, version: null };
}

// One scope as a run context: a workflow or Workspace scope also falls back to global.
export function contextOf(scope: ScopeRef): Partial<Record<PromptScopeType, string | null>> {
  return scope.scope_type === "global" ? {} : { [scope.scope_type]: scope.scope_id };
}

// Where the text a run gets comes from: "the shipped text", "the global text", "the text from workspace Payments".
export function sourceLabel(scope: ScopeRef | null, names: Map<string, string>): string {
  if (!scope) return "the shipped text";
  if (scope.scope_type === "global" || !scope.scope_id) return "the global text";
  return `the text from ${SCOPE_LABEL[scope.scope_type].toLowerCase()} ${names.get(scopeKey(scope)) ?? scope.scope_id}`;
}

// The scopes to choose from in the drawer: what the server says the user may write, plus every scope that already
// has a text the user can see (the detail lists only those); global first, then workflows and Workspaces by name.
export function scopeChoices(
  writable: PromptWritableScope[] | undefined,
  templates: PromptTemplateView[],
  extra: ScopeRef | null = null,
): Array<ScopeRef & { label: string; writable: boolean }> {
  const byKey = new Map<string, ScopeRef & { label: string; writable: boolean }>();
  const add = (scope: ScopeRef, label: string | null | undefined, canWrite: boolean) => {
    const key = scopeKey(scope);
    const known = byKey.get(key);
    byKey.set(key, {
      scope_type: scope.scope_type,
      scope_id: scope.scope_type === "global" ? null : scope.scope_id,
      label: label || known?.label || (scope.scope_id ?? "Global"),
      writable: canWrite || Boolean(known?.writable),
    });
  };
  add(GLOBAL_SCOPE, "Global", false);
  for (const scope of writable ?? []) add(scope, scope.label, true);
  for (const template of templates) add(template, null, false);
  if (extra) add(extra, null, false);
  const order: Record<string, number> = { global: 0, workflow: 1, workspace: 2 };
  return [...byKey.values()].sort(
    (a, b) => (order[a.scope_type] ?? 9) - (order[b.scope_type] ?? 9) || a.label.localeCompare(b.label),
  );
}

export function scopeNames(choices: Array<ScopeRef & { label: string }>): Map<string, string> {
  return new Map(choices.map((choice) => [scopeKey(choice), choice.label]));
}

// --- Sub-groups and placeholder meanings come from the backend key spec (no tables here) ----------------------

export const OTHER_GROUP = "Other";

export function subGroupsOf<T extends { group?: string | null; group_order?: number | null }>(
  items: T[],
): Array<{ label: string; items: T[] }> {
  const groups = new Map<string, { order: number; items: T[] }>();
  for (const item of items) {
    const label = item.group?.trim() || OTHER_GROUP;
    const order = label === OTHER_GROUP ? Infinity : (item.group_order ?? Number.MAX_SAFE_INTEGER);
    const known = groups.get(label);
    groups.set(label, { order: Math.min(known?.order ?? Infinity, order), items: [...(known?.items ?? []), item] });
  }
  // The server's group_order; groups without one in first-seen order after them; "Other" last.
  return [...groups.entries()]
    .sort(([, a], [, b]) => (a.order === b.order ? 0 : a.order < b.order ? -1 : 1))
    .map(([label, group]) => ({ label, items: group.items }));
}

export function placeholderMeanings(
  placeholders: string[],
  descriptions: Record<string, string> | undefined,
): Array<{ name: string; meaning: string | null }> {
  return placeholders.map((name) => ({ name, meaning: descriptions?.[name]?.trim() || null }));
}
