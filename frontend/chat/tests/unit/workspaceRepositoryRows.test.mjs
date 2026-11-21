// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceRepositoryRows.test.mjs
//
// UI: Work › Repositories said "No repository connected yet" while the Demo Shop's workflow runs used the
// repository record CHEF/kitchen-helper-mini. The page merges the Workspace's repository records with its Knowledge
// git sources: one row per repository.
import assert from "node:assert/strict";
import { test } from "node:test";
import { workspaceRepositoryRows } from "../../src/chat/coding/repository/workspaceRepositoryRows.ts";

const record = (id, name, extra = {}) => ({
  id, name, provider: "bitbucket", default_branch: "main", source: { kind: "bitbucket", name }, owners: [],
  coding_setup: { configured: ["build", "test"], missing: ["lint"] }, last_index_status: "not_indexed", ...extra,
});

test("a record no source names is listed on its own, with its origin, branch and coding setup", () => {
  const rows = workspaceRepositoryRows([record("w1", "CHEF/kitchen-helper-mini")], []);
  assert.equal(rows.length, 1);
  const [row] = rows;
  assert.equal(row.kind, "record");
  assert.deepEqual([row.name, row.origin, row.branch, row.status, row.recordId], ["CHEF/kitchen-helper-mini", "Bitbucket", "main", "–", "w1"]);
  assert.deepEqual(row.setup, { text: "Lint missing", missing: true });
  assert.equal(row.canSetUp, false);
});

test("a record and the Knowledge source of the same repository are one source row with the record's setup", () => {
  const source = { id: "c1", name: "scm/chef/Kitchen-helper-mini", commit: "b2" };
  const rows = workspaceRepositoryRows([record("w1", "CHEF/kitchen-helper-mini")], [source]);
  assert.equal(rows.length, 1);
  assert.deepEqual([rows[0].kind, rows[0].canSetUp, rows[0].branch, rows[0].recordId], ["source", false, "main", "w1"]);
});

test("a synced source without a record can be set up; one without a commit cannot", () => {
  const rows = workspaceRepositoryRows([], [{ id: "c1", name: "scm/ACME/shop", commit: "a1" }, { id: "c2", name: "scm/ACME/other", commit: null }]);
  assert.deepEqual(rows.map((row) => [row.kind, row.canSetUp, row.recordId, row.setup]), [
    ["source", true, null, null], ["source", false, null, null]]);
});

test("order: records first, then sources; a duplicate record is listed once", () => {
  const rows = workspaceRepositoryRows(
    [record("w1", "CHEF/kitchen-helper-mini"), record("w2", "CHEF/kitchen-helper-mini")],
    [{ id: "c9", name: "scm/ACME/other", commit: null }]);
  assert.deepEqual(rows.map((row) => row.kind), ["record", "source"]);
  assert.equal(rows[0].id, "w1");
});

test("no records and no sources: no rows (the empty state); malformed records are ignored", () => {
  assert.deepEqual(workspaceRepositoryRows([], []), []);
  assert.deepEqual(workspaceRepositoryRows([{ id: 1 }, null].filter(Boolean), []), []);
});

test("a branch the API reads from the Knowledge source is marked as such; a stored one is not", () => {
  const [fromSource] = workspaceRepositoryRows([record("w1", "octryx/kitchen-helper", { default_branch_from: "knowledge_source" })], []);
  assert.deepEqual([fromSource.branch, fromSource.branchFromSource], ["main", true]);
  const [stored] = workspaceRepositoryRows([record("w2", "repos/demo-shop")], []);
  assert.equal(stored.branchFromSource, false);
});
