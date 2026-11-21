// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/repositoryRunsModel.test.mjs
//
// Work › Repositories › Runs: a repository's latest workflow runs, read when its panel opens
// from GET /api/v1/workflow-runs?view=work&repository_id=….
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  recentRepositoryRuns, repositoryRunsPath, runsCountText, runsErrorText,
} from "../../src/chat/coding/repository/repositoryRunsModel.ts";
import { workspaceRepositoryRows } from "../../src/chat/coding/repository/workspaceRepositoryRows.ts";

const run = (n, extra = {}) => ({
  id: `run-${n}`, title: `Run ${n}`, workflow_key: "epic-delivery", workflow_kind: "graph", status: "completed",
  waiting_kind: null, pause_reason: null, outcome: null, session_id: `s-${n}`, branch: "feature/x",
  created_at: `2026-11-${String(n).padStart(2, "0")}T08:00:00Z`, updated_at: `2026-11-${String(n).padStart(2, "0")}T09:00:00Z`,
  cost: 0.5, ...extra,
});

test("the read asks for one record's runs with the Work › Runs extras", () => {
  const url = new URL(repositoryRunsPath("rec 1"), "http://x");
  assert.equal(url.pathname, "/api/v1/workflow-runs");
  assert.equal(url.searchParams.get("repository_id"), "rec 1");
  assert.equal(url.searchParams.get("view"), "work");
});

test("the latest ten runs first, each in the words of Work › Runs and linked to its chat", () => {
  const runs = Array.from({ length: 12 }, (_, i) => run(i + 1));
  const rows = recentRepositoryRuns(runs);
  assert.equal(rows.length, 10);
  assert.deepEqual(rows.slice(0, 2).map((row) => row.key), ["run-12", "run-11"]);
  const [first] = rows;
  assert.deepEqual([first.status, first.tone, first.branch, first.cost, first.href],
    ["Done", "neutral", "feature/x", "$0.50", "/chat?session_id=s-12"]);
  assert.equal(runsCountText(runs.length, rows.length), "The latest 10 of 12 runs.");
  assert.equal(runsCountText(3, 3), "");
});

test("a waiting run needs the person; a run without chat or branch says so plainly", () => {
  const [row] = recentRepositoryRuns([run(1, { status: "waiting", session_id: null, branch: " ", cost: 0,
    work_item: { key: "OCX-7", title: "Retry checkout" } })]);
  assert.deepEqual([row.name, row.status, row.tone, row.href, row.branch, row.cost],
    ["OCX-7 · Retry checkout", "Needs you", "attention", null, null, "–"]);
});

test("a record that no longer exists is said as such; other failures ask to try again", () => {
  assert.match(runsErrorText("This repository record does not exist."), /no longer exists/);
  assert.match(runsErrorText("Internal Server Error"), /could not be loaded/);
});

test("each row names the record whose runs it lists; a source without a record has none", () => {
  const record = { id: "w1", name: "CHEF/kitchen-helper-mini", provider: "bitbucket", default_branch: "main",
    source: { kind: "bitbucket", name: "CHEF/kitchen-helper-mini" }, owners: [], coding_setup: { configured: [], missing: [] } };
  const rows = workspaceRepositoryRows([record], [{ id: "c1", name: "scm/ACME/other", commit: null }]);
  assert.deepEqual(rows.map((row) => [row.kind, row.recordId]), [["record", "w1"], ["source", null]]);
});
