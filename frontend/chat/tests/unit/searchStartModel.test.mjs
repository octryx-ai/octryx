// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/searchStartModel.test.mjs
//
// UI check (K-Search): Knowledge › Search before the first search shows example questions made from the
// workspace's sources and the sources with their state. The rules, without React.
import assert from "node:assert/strict";
import { test } from "node:test";
import { exampleQuestions, START_SOURCE_LIMIT, startSources } from "../../src/admin/components/workspaceKnowledge/search/searchStartModel.ts";

const NOW = Date.parse("2026-11-09T12:00:00Z");
const synced = { state: "completed", started_at: "2026-11-09T10:00:00Z", finished_at: "2026-11-09T10:05:00Z" };
const connector = (key, kind, scope = {}, overrides = {}) => ({
  connector_key: key, kind, scope, products: [], version: null, max_items_per_run: 100, state: "active", cursor: {},
  schedule: { enabled: true, interval_minutes: 60, instance_enabled: true }, running: false, last_run: synced, served_items: 5,
  ...overrides,
});

test("questions name each source the way a person would: a space, a project, a repository, a cluster", () => {
  assert.deepEqual(exampleQuestions([
    connector("c", "confluence", { spaces: ["ENG", "OPS"] }),
    connector("j", "jira", { project_keys: ["PAY"] }),
    connector("g", "git_repository", { remote: "https://bitbucket.example/scm/acme/billing-service.git" }),
    connector("k", "kubernetes", { cluster: "dev-eu" }),
  ]), ["What is documented in ENG?", "Which PAY issues are still open?", "How is billing-service configured?"]);
  assert.deepEqual(exampleQuestions([connector("k", "kubernetes", { cluster: "dev-eu" })]), ["Which services run in dev-eu?"]);
  assert.deepEqual(exampleQuestions([connector("x", "notion")]), ["What is in x?"]);
});

test("no question about a source with nothing to find yet, or a paused one; uploads fill up by their titles", () => {
  const never = connector("n", "confluence", { spaces: ["NEW"] }, { last_run: null, served_items: 0 });
  const paused = connector("p", "jira", { project_keys: ["OLD"] }, { state: "paused" });
  const docs = [
    { source_id: "1", source_key: "a", display_title: "Operations handbook.docx", revision_count: 1, latest_revision_ordinal: 1, origin: { type: "upload" } },
    { source_id: "2", source_key: "b", display_title: "ENG page", revision_count: 1, latest_revision_ordinal: 1,
      origin: { type: "connector", connector_kind: "confluence" } },
  ];
  assert.deepEqual(exampleQuestions([never, paused], docs), ["What does Operations handbook say?"]);
  assert.deepEqual(exampleQuestions([], []), []);
});

test("at most three questions, never the same one twice", () => {
  const many = ["A", "B", "C", "D"].map((space) => connector(space, "confluence", { spaces: [space] }));
  assert.equal(exampleQuestions(many).length, 3);
  assert.deepEqual(exampleQuestions([connector("1", "jira", { project_keys: ["X"] }), connector("2", "jira", { project_keys: ["X"] })]),
    ["Which X issues are still open?"]);
});

test("sources: the ones needing attention first, at most six, each with its state, last sync and reason", () => {
  const failed = connector("broken", "jira", {}, { last_run: { state: "failed", reason: "source_unauthorized" } });
  const rows = startSources([connector("ok", "confluence"), failed], true, NOW);
  assert.deepEqual(rows.map((row) => [row.key, row.origin, row.state]), [["broken", "Jira", "Needs attention"], ["ok", "Confluence", "Up to date"]]);
  assert.match(rows[0].reason, /credential/);
  assert.equal(rows[1].at, Date.parse("2026-11-09T10:05:00Z"));
  const eight = Array.from({ length: 8 }, (_, index) => connector(`s${index}`, "confluence"));
  assert.equal(startSources(eight, true, NOW).length, START_SOURCE_LIMIT);
});
