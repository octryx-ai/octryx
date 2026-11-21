import assert from "node:assert/strict";
import { test } from "node:test";
import {
  changeSummary, markChanged, mergeKpis, previewPaths, resolutionIssue, reviewAction, timelineIndex, unacknowledgedHigh,
  updateFailure, withResolution,
} from "../../src/admin/components/skillCatalog/skillUpdateModel.ts";

const short = (commit) => (commit ? commit.slice(0, 8) : "—");
const conflict = {
  id: "c-1", path: "SKILL.md", kind: "hunk",
  base: ["- a\n", "- b\n"], ours: ["- a\n", "- b\n", "- mine\n"], theirs: ["See SECURITY.md\n"],
  relocation: { path: "SECURITY.md", line: 10, end_line: 11, after_line: 11, block: ["- a\n", "- b\n"], mine: ["- a\n", "- b\n", "- mine\n"] },
};
const report = {
  files: [
    { path: "LICENSE", status: "unchanged" },
    { path: "SECURITY.md", status: "added_upstream" },
    { path: "SKILL.md", status: "conflict", local_hunks: 1, upstream_hunks: 2 },
  ],
  conflicts: [conflict], resolutions: {},
  base_commit: "0374056f00000000", theirs_commit: "4451ceca00000000", from_version: 2, path_moved: null,
};

test("the local lines of a conflict are the lines of ours that are not in base", () => {
  assert.deepEqual(markChanged(conflict.base, conflict.ours, "loc").map((line) => line.mark), ["", "", "loc"]);
  assert.deepEqual(markChanged(conflict.base, conflict.theirs, "add"), [{ text: "See SECURITY.md", mark: "add" }]);
});

test("merge KPIs count changed files, merged local hunks and open conflicts", () => {
  const kpis = mergeKpis(report, short);
  assert.equal(kpis.commits, "0374056f → 4451ceca");
  assert.equal(kpis.filesChanged, 2);
  assert.equal(kpis.mergedLocal, 1);
  assert.deepEqual([kpis.open, kpis.resolved], [1, 0]);
  const resolved = { ...report, resolutions: { "c-1": { choice: "relocate" } } };
  assert.deepEqual([mergeKpis(resolved, short).open, mergeKpis(resolved, short).resolved], [0, 1]);
});

test("a resolution keeps the saved ones and manual text is required", () => {
  const saved = { ...report, resolutions: { other: { choice: "mine" } } };
  assert.deepEqual(withResolution(saved, "c-1", { choice: "upstream" }), { other: { choice: "mine" }, "c-1": { choice: "upstream" } });
  assert.match(resolutionIssue({ choice: "manual", text: "  " }, conflict), /merged text/);
  assert.equal(resolutionIssue({ choice: "relocate" }, conflict), null);
  assert.match(resolutionIssue({ choice: "relocate" }, { ...conflict, relocation: null }), /cannot be applied/);
});

test("previews show SKILL.md first, then added and relocation targets that exist", () => {
  assert.deepEqual(previewPaths(report, ["LICENSE", "SECURITY.md", "SKILL.md"]), ["SKILL.md", "SECURITY.md"]);
  assert.deepEqual(previewPaths(report, ["SKILL.md"]), ["SKILL.md"]);
});

test("upstream update refusals are told apart by code", () => {
  assert.equal(updateFailure({ code: "skill_upstream_path_missing" }), "path_missing");
  assert.equal(updateFailure({ code: "skill_draft_exists" }), "draft_exists");
  assert.equal(updateFailure({ code: "skill_up_to_date" }), "up_to_date");
  assert.equal(updateFailure(new Error("boom")), "other");
});

test("the drawer's primary action follows the four-eyes state", () => {
  const viewer = (can) => ({ is_author: !can, is_submitter: !can, can_approve: can });
  const inReview = { state: "in_review" };
  assert.equal(reviewAction({ state: "draft" }, null), "submit");
  assert.equal(reviewAction(inReview, { status: "pending", viewer: viewer(true) }), "approve");
  assert.equal(reviewAction(inReview, { status: "pending", viewer: viewer(false) }), null);
  assert.equal(reviewAction(inReview, { status: "approved", viewer: viewer(false) }), "publish");
  assert.equal(reviewAction(null, null), null);
  // Single-admin approval rule: the author publishes a draft or their pending review in one step.
  assert.equal(reviewAction({ state: "draft" }, null, true), "publish_own");
  assert.equal(reviewAction(inReview, { status: "pending", viewer: viewer(false) }, true), "publish_own");
  assert.equal(reviewAction(inReview, { status: "approved", viewer: viewer(false) }, true), "publish");
  assert.deepEqual([timelineIndex("draft"), timelineIndex("in_review"), timelineIndex("published")], [0, 1, 2]);
});

test("summary texts and unacknowledged high findings", () => {
  assert.equal(changeSummary({ version: 1, base_version: null, note: null, merge_report: null }, short), "New skill");
  assert.equal(changeSummary({ version: 3, base_version: 2, note: "x", merge_report: report }, short), "Upstream 4451ceca + local customizations");
  const version = {
    acknowledged_findings: ["f1"],
    security_report: { findings: [{ id: "f1", severity: "high" }, { id: "f2", severity: "high" }, { id: "f3", severity: "info" }] },
  };
  assert.deepEqual(unacknowledgedHigh(version).map((finding) => finding.id), ["f2"]);
});
