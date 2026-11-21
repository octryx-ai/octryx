import assert from "node:assert/strict";
import { test } from "node:test";
import { assignedByLabel, flattenCategories, hasOpenConflicts, nameIssue, refusalText, splitSkillMd, stateBadge, usageSplit, versionLine } from "../../src/admin/components/skillCatalog/skillCatalogModel.ts";
import { foldDiff } from "../../src/admin/components/skillCatalog/skillDiffModel.ts";

test("refusals become fixed sentences; unknown codes fall back to the message, never to the raw object", () => {
  assert.match(refusalText(Object.assign(new Error("x"), { code: "skill_self_approval", status: 409 })), /another platform admin/);
  assert.equal(refusalText({ status: 403 }), "Platform admin role required.");
  assert.equal(refusalText(new Error("boom")), "Refused: boom.");
  assert.equal(refusalText({ detail: { secret: "s" } }), "The request failed.");
});

test("versions, states and assignment sources read like the mock", () => {
  assert.equal(versionLine({ published: { version: 2 }, open: { version: 3, state: "in_review" } }), "v2 · v3 in review");
  assert.equal(versionLine({ published: null, open: null }), "retired");
  assert.equal(stateBadge("draft"), "work-badge work-badge--attention");
  assert.equal(stateBadge("unknown"), "work-badge work-badge--neutral");
  assert.equal(assignedByLabel("category:iac", { iac: "Infrastructure as code" }), "Category Infrastructure as code");
  assert.equal(assignedByLabel(""), "Not assigned");
});

test("the Agent Skills name rule refuses what the server refuses", () => {
  for (const bad of ["", "Bad", "-a", "a-", "a--b", "a b", "x".repeat(65)]) assert.ok(nameIssue(bad), bad);
  assert.equal(nameIssue("style-guide-2"), null);
});

test("frontmatter split, category flattening, usage split and open conflicts", () => {
  assert.deepEqual(splitSkillMd("---\nname: a\n---\n\n# A\n"), { frontmatter: "name: a", body: "\n# A\n" });
  assert.deepEqual(splitSkillMd("# no frontmatter"), { frontmatter: "", body: "# no frontmatter" });
  const flat = flattenCategories([{ key: "a", label: "A", children: [{ key: "a.b", label: "B", children: [] }] }]);
  assert.deepEqual(flat.map((row) => [row.key, row.depth, row.fullLabel]), [["a", 0, "A"], ["a.b", 1, "A / B"]]);
  assert.deepEqual(usageSplit({ "platform_chat:get": 2, "octryx_claude:slash": 1 }), { chat: 2, model: 0, slash: 1 });
  const report = { conflicts: [{ id: "c-1" }], resolutions: {} };
  assert.equal(hasOpenConflicts(report), true);
  assert.equal(hasOpenConflicts({ ...report, resolutions: { "c-1": { choice: "mine" } } }), false);
  assert.equal(hasOpenConflicts(null), false);
});

test("a diff keeps two context lines around each change and folds the rest", () => {
  const same = (text) => ({ kind: "same", text });
  const rows = foldDiff([same("1"), same("2"), same("3"), same("4"), { kind: "added", text: "x" }, same("5"), same("6"), same("7")]);
  assert.deepEqual(rows.map((row) => row.kind === "hunk" ? row.text : row.text), ["… 2 unchanged lines", "3", "4", "x", "5", "6", "… 1 unchanged line"]);
});
