import type { Assignment, AssignmentMode, AssignmentPolicy, AssignmentSkill, Readiness } from "./skillDeliveryTypes";
import type { CategoryNode, Surface } from "./skillCatalogTypes";

// Workspace → Skills (WP 2.7): the local edit state of a Workspace's skill assignment. Edits stay local until
// Save; the server recomputes the effective set, so the only local number is a preview of what is assigned before
// the surface and readiness checks. Pure functions only (tests/unit/workspaceSkillsModel.test.mjs).

export const MODE_CHOICES: { mode: AssignmentMode; title: string; text: string }[] = [
  { mode: "all_active", title: "All published", text: "Every published skill that is available on a surface." },
  { mode: "selected_only", title: "Selected categories and skills", text: "Only what is ticked below." },
  { mode: "none", title: "None", text: "No catalog skills in this Workspace." },
];

const unique = (values: string[]) => [...new Set(values)].sort();
const toggle = (values: string[], value: string) => (values.includes(value) ? values.filter((item) => item !== value) : [...values, value]);

export function draftFrom(policy: AssignmentPolicy): AssignmentPolicy {
  return {
    mode: policy.mode,
    skill_ids: [...policy.skill_ids],
    category_keys: [...policy.category_keys],
    blocked_skill_ids: [...policy.blocked_skill_ids],
    surfaces: { ...policy.surfaces },
  };
}

/** The PUT body: the whole state, lists de-duplicated and sorted. */
export function saveBody(draft: AssignmentPolicy): AssignmentPolicy {
  return {
    mode: draft.mode,
    skill_ids: unique(draft.skill_ids),
    category_keys: unique(draft.category_keys),
    blocked_skill_ids: unique(draft.blocked_skill_ids),
    surfaces: { platform_chat: Boolean(draft.surfaces.platform_chat), octryx_claude: Boolean(draft.surfaces.octryx_claude) },
  };
}

export function isDirty(draft: AssignmentPolicy, saved: AssignmentPolicy): boolean {
  return JSON.stringify(saveBody(draft)) !== JSON.stringify(saveBody(saved));
}

export const setMode = (draft: AssignmentPolicy, mode: AssignmentMode): AssignmentPolicy => ({ ...draft, mode });
export const setSurface = (draft: AssignmentPolicy, surface: Surface, on: boolean): AssignmentPolicy =>
  ({ ...draft, surfaces: { ...draft.surfaces, [surface]: on } });
export const toggleCategory = (draft: AssignmentPolicy, key: string): AssignmentPolicy =>
  ({ ...draft, category_keys: toggle(draft.category_keys, key) });
export const toggleSkill = (draft: AssignmentPolicy, skillId: string): AssignmentPolicy =>
  ({ ...draft, skill_ids: toggle(draft.skill_ids, skillId) });
export const toggleBlocked = (draft: AssignmentPolicy, skillId: string): AssignmentPolicy =>
  ({ ...draft, blocked_skill_ids: toggle(draft.blocked_skill_ids, skillId) });

/** The whole-category key that covers `categoryKey` (itself or its parent), or null. */
export function coveringCategory(draft: AssignmentPolicy, categoryKey: string | null): string | null {
  if (!categoryKey) return null;
  return draft.category_keys.find((key) => categoryKey === key || categoryKey.startsWith(`${key}.`)) ?? null;
}

/** A child category ticked through its parent: shown checked and locked. */
export function categoryLocked(draft: AssignmentPolicy, node: CategoryNode): boolean {
  const covering = coveringCategory(draft, node.key);
  return covering !== null && covering !== node.key;
}

export function categoryChecked(draft: AssignmentPolicy, node: CategoryNode): boolean {
  return coveringCategory(draft, node.key) !== null;
}

/** A skill inside a ticked category: shown checked and locked. */
export function skillLocked(draft: AssignmentPolicy, skill: Pick<AssignmentSkill, "category_key">): boolean {
  return coveringCategory(draft, skill.category_key) !== null;
}

export function skillChecked(draft: AssignmentPolicy, skill: Pick<AssignmentSkill, "id" | "category_key">): boolean {
  return draft.skill_ids.includes(skill.id) || skillLocked(draft, skill);
}

/** Assigned before the surface checks: what the mode, the ticks and the blocks select (blocked always wins). */
export function isAssigned(draft: AssignmentPolicy, skill: Pick<AssignmentSkill, "id" | "category_key">): boolean {
  if (draft.mode === "none" || draft.blocked_skill_ids.includes(skill.id)) return false;
  return draft.mode === "all_active" || skillChecked(draft, skill);
}

export function previewCount(draft: AssignmentPolicy, skills: Pick<AssignmentSkill, "id" | "category_key">[]): number {
  return skills.filter((skill) => isAssigned(draft, skill)).length;
}

/** Distinct skills the server delivers on at least one surface. */
export function effectiveCount(view: Pick<Assignment, "effective">): number {
  return new Set(Object.values(view.effective).flatMap((rows) => rows.map((row) => row.skill_id))).size;
}

/** The published skills filed directly under one category key. */
export function skillsIn(skills: AssignmentSkill[], categoryKey: string): AssignmentSkill[] {
  return skills.filter((skill) => skill.category_key === categoryKey);
}

/** Skills whose category is not in the (non-archived) tree, so the picker still lists them. */
export function skillsOutsideTree(skills: AssignmentSkill[], nodes: CategoryNode[]): AssignmentSkill[] {
  const keys = new Set(nodes.flatMap((node) => [node.key, ...node.children.map((child) => child.key)]));
  return skills.filter((skill) => !skill.category_key || !keys.has(skill.category_key));
}

export function refusalLines(readiness: Readiness | null | undefined): string[] {
  return (readiness?.refusals ?? []).map((refusal) => [refusal.tool, refusal.policy, refusal.rule].filter(Boolean).join(" · "));
}

export function isConflict(error: unknown): boolean {
  return Boolean(error) && typeof error === "object" && (error as { code?: unknown }).code === "skill_assignment_conflict";
}
