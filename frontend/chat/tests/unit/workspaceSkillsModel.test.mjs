import assert from "node:assert/strict";
import { test } from "node:test";
import {
  categoryChecked, categoryLocked, draftFrom, effectiveCount, isAssigned, isConflict, isDirty, previewCount, refusalLines,
  saveBody, setMode, setSurface, skillChecked, skillLocked, toggleBlocked, toggleCategory, toggleSkill,
} from "../../src/admin/components/skillCatalog/workspaceSkillsModel.ts";

const policy = {
  mode: "selected_only",
  skill_ids: [],
  category_keys: [],
  blocked_skill_ids: [],
  surfaces: { platform_chat: true, octryx_claude: true },
};
const skills = [
  { id: "a", category_key: "iac.terraform" },
  { id: "b", category_key: "iac" },
  { id: "c", category_key: "diagnosis" },
];
const child = { key: "iac.terraform" };
const parent = { key: "iac" };

test("a whole category checks and locks its child categories and skills", () => {
  const draft = toggleCategory(draftFrom(policy), "iac");
  assert.equal(categoryChecked(draft, parent), true);
  assert.equal(categoryLocked(draft, parent), false);
  assert.equal(categoryChecked(draft, child), true);
  assert.equal(categoryLocked(draft, child), true);
  assert.equal(skillLocked(draft, skills[0]), true);
  assert.equal(skillChecked(draft, skills[1]), true);
  assert.equal(skillChecked(draft, skills[2]), false);
  assert.equal(previewCount(draft, skills), 2);
  // A sibling key with the same prefix is not covered.
  assert.equal(skillLocked(draft, { id: "x", category_key: "iac-tools" }), false);
});

test("single skills, modes and blocks: blocked always wins", () => {
  let draft = toggleSkill(draftFrom(policy), "c");
  assert.equal(previewCount(draft, skills), 1);
  draft = toggleBlocked(draft, "c");
  assert.equal(isAssigned(draft, skills[2]), false);
  draft = setMode(draft, "all_active");
  assert.equal(previewCount(draft, skills), 2);
  assert.equal(previewCount(setMode(draft, "none"), skills), 0);
  assert.deepEqual(toggleSkill(toggleSkill(draftFrom(policy), "c"), "c").skill_ids, []);
});

test("dirty tracking and the PUT body carry the whole state", () => {
  const draft = draftFrom(policy);
  assert.equal(isDirty(draft, policy), false);
  const edited = setSurface(toggleCategory(toggleSkill(draft, "b"), "iac"), "octryx_claude", false);
  assert.equal(isDirty(edited, policy), true);
  assert.deepEqual(policy.skill_ids, [], "the saved policy is not mutated");
  assert.deepEqual(saveBody({ ...edited, skill_ids: ["b", "a", "b"] }), {
    mode: "selected_only",
    skill_ids: ["a", "b"],
    category_keys: ["iac"],
    blocked_skill_ids: [],
    surfaces: { platform_chat: true, octryx_claude: false },
  });
  // Order of the lists does not make a draft dirty.
  assert.equal(isDirty({ ...policy, skill_ids: ["b", "a"] }, { ...policy, skill_ids: ["a", "b"] }), false);
});

test("effective count, refusal lines and the conflict refusal", () => {
  const view = { effective: { platform_chat: [{ skill_id: "a" }, { skill_id: "b" }], octryx_claude: [{ skill_id: "a" }] } };
  assert.equal(effectiveCount(view), 2);
  assert.deepEqual(refusalLines({ state: "restricted", refusals: [{ tool: "run_kubectl", policy: "tool_policy", reason: "x", rule: null }] }),
    ["run_kubectl · tool_policy"]);
  assert.deepEqual(refusalLines(undefined), []);
  assert.equal(isConflict({ code: "skill_assignment_conflict", status: 409 }), true);
  assert.equal(isConflict(new Error("x")), false);
});
