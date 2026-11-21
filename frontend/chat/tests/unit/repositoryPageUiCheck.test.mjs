// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/repositoryPageUiCheck.test.mjs
//
// UI check (Work › Repositories, three Bitbucket repositories, none set up yet):
// R1 skeleton rows and "No repository connected yet" showed together for ~3 s; R2 the address got `work_item_id`
// unasked; R3 no access mode; R4 a source whose sync failed on Git access read "Waiting for sync"; R5 "From" said
// "Knowledge source"; R6 "Set up" stood on every row and did not say what it does.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { useWorkspaceRepositoryList } from "../../src/chat/coding/repository/useWorkspaceRepositoryList.ts";
import { useKnowledgePermissionState } from "../../src/chat/knowledge/useKnowledgePermissions.ts";
import { sourceRows, sourceStatus } from "../../src/chat/coding/repository/repositoryPresenter.ts";
import { workspaceRepositoryRows } from "../../src/chat/coding/repository/workspaceRepositoryRows.ts";
import { reasonText } from "../../src/admin/components/workspaceKnowledge/connectorReasons.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
const source = (relative) => readFileSync(new URL(`../../src/${relative}`, import.meta.url), "utf8");

const demo_shop = {
  id: "s1", name: "scm/acme/demo-shop", commit: null, fetch_mode: "remote_git", access_mode: "read_write",
  connection: { name: "Shop Bitbucket", type: "bitbucket" }, last_sync: { state: "failed", reason: "source_unauthorized" },
};
const synced = {
  id: "s2", name: "scm/SHOP/server", commit: "a".repeat(40), fetch_mode: "remote_git", access_mode: "read_only",
  connection: { name: "Bitbucket", type: "bitbucket" }, last_sync: { state: "completed", reason: null },
};
const snapshot = { id: "s3", name: "acme/local", commit: "b".repeat(40), fetch_mode: "local_snapshot", access_mode: null,
  connection: null, last_sync: null };

test("Each row says what agents may do on it and through which connection it is read", () => {
  const [z, s, local] = sourceRows([demo_shop, synced, snapshot]);
  assert.deepEqual([z.access, s.access, local.access], ["Read and write", "Read only", "–"]);
  assert.deepEqual([z.origin, s.origin, local.origin], ["Bitbucket · Shop Bitbucket", "Bitbucket", "Snapshot"]);
  assert.match(z.originTitle, /Bitbucket connection "Shop Bitbucket"/);
  // A record set up from a source keeps the source's origin and access, and opens its runs.
  const [bound] = workspaceRepositoryRows([{ id: "r", name: "scm/acme/demo-shop", provider: "knowledge_snapshot",
    default_branch: null, source: { kind: "knowledge_source", name: "demo-shop" }, owners: [],
    coding_setup: { configured: [], missing: [] }, last_index_status: "not_indexed" }], [demo_shop]);
  assert.deepEqual([bound.origin, bound.access, bound.recordId, bound.canSetUp], ["Bitbucket · Shop Bitbucket", "Read and write", "r", false]);
  // A row that does not say how a source is read keeps the generic wording.
  const [older] = sourceRows([{ id: "o", name: "scm/a/b", commit: null }]);
  assert.deepEqual([older.origin, older.access, older.status], ["Knowledge source", "–", "Waiting for sync"]);
});

test("A failed sync says why instead of a generic wait", () => {
  const failed = sourceStatus(demo_shop);
  assert.deepEqual([failed.label, failed.tone], ["Sync failed: no Git access", "problem"]);
  assert.match(failed.title, /rejected the connection's credential.*Set a Git token/);
  const other = sourceStatus({ ...demo_shop, last_sync: { state: "failed", reason: "repository_too_large" } });
  assert.equal(other.label, "Sync failed");
  assert.match(other.title, /exceeds the configured file or size limits/);
  assert.equal(sourceStatus({ ...demo_shop, last_sync: { state: "running", reason: null } }).label, "Syncing");
  assert.equal(sourceStatus({ ...demo_shop, last_sync: null }).label, "Waiting for sync");
  assert.equal(sourceStatus(synced).label, "Synced");
  assert.equal(sourceStatus({ ...snapshot, commit: null }).label, "Waiting for upload");
  // A failure after an earlier sync keeps that commit, and says so.
  assert.match(sourceStatus({ ...synced, last_sync: { state: "failed", reason: "git_token_invalid" } }).title,
    /last synced commit stays available/);
});

test("an empty repository is no failure: it reads as ready for a first commit", () => {
  const empty = { ...demo_shop, last_sync: { state: "completed", reason: "repository_empty" } };
  const state = sourceStatus(empty);
  assert.deepEqual([state.label, state.tone], ["Empty repository — ready for a first commit", "neutral"]);
  assert.match(state.title, /no commits yet.*Push a first commit/);
  const [row] = sourceRows([empty]);
  assert.deepEqual([row.status, row.tone, row.canSetUp], ["Empty repository — ready for a first commit", "neutral", false]);
  // Knowledge › Sources shows the completed run's reason in the same words.
  assert.match(reasonText("repository_empty"), /^empty repository — ready for a first commit/);
});

test("Setting up for runs is offered on a synced source without a record only, under a label that says what it does", () => {
  const rows = sourceRows([demo_shop, synced, snapshot]);
  assert.deepEqual(rows.map((row) => row.canSetUp), [false, true, true]);
  const page = source("chat/coding/repository/RepositoryPage.tsx");
  assert.match(page, /if \(!mayAuthor \|\| !row\.canSetUp\) return null;/);
  assert.match(page, />Set up for runs<\/button>/);
  assert.doesNotMatch(page, />Set up<\/button>/);
  assert.match(page, /header: "Access"/);
});

test("The sources and the permission read say when they are in", async () => {
  const previousFetch = globalThis.fetch;
  const pending = [];
  globalThis.fetch = (url, options) => new Promise((resolve) => pending.push({ url: String(url), options, resolve }));
  let current; let renderer;
  function Probe() { current = useWorkspaceRepositoryList("workspace-a", true); return null; }
  const response = (data) => ({ ok: true, json: async () => data });
  try {
    act(() => { renderer = TestRenderer.create(createElement(Probe)); });
    const records = pending.find((item) => item.url.endsWith("/repositories"));
    const sources = pending.find((item) => item.url.endsWith("/repositories/sources"));
    await act(async () => records.resolve(response({ items: [] })));
    assert.equal(current.recordsListed, true);
    assert.equal(current.sourcesListed, false, "no repository yet is not \"none connected\" while sources load");
    await act(async () => sources.resolve(response({ items: [synced] })));
    assert.equal(current.sourcesListed, true);
    assert.equal(current.sources.length, 1);
  } finally {
    act(() => renderer?.unmount()); globalThis.fetch = previousFetch;
  }

  let answer; let state; let probe;
  const load = () => new Promise((resolve) => { answer = resolve; });
  function Permission() { state = useKnowledgePermissionState("workspace-a", load); return null; }
  try {
    act(() => { probe = TestRenderer.create(createElement(Permission)); });
    assert.deepEqual(state, { resolved: false, mayAuthor: false });
    await act(async () => answer({ may_author: true }));
    assert.deepEqual(state, { resolved: true, mayAuthor: true });
  } finally {
    act(() => probe?.unmount());
  }

  const list = source("chat/coding/repository/RepositoryList.tsx");
  assert.match(list, /listed = list\.recordsListed && permission\.resolved && \(!mayAuthor \|\| list\.sourcesListed\)/);
  assert.match(list, /!listed \? <LoadingState label="repositories" \/> : <RepositoryOverview/);
  // The Sessions skeleton belongs to the Sessions pages, not under Work › Repositories.
  assert.match(source("chat/coding/CodingAreaWorkspace.tsx"), /\{loading && activeQueue \? <LoadingState label="coding sessions"/);
});

test("The first session picked is not written into the address, on any page", () => {
  const page = [source("chat/coding/CodingAreaWorkspace.tsx"), source("chat/coding/useCodingAreaState.ts")].join("\n");
  // The read writes only the session that was asked for (codingSelectionAddress.test.mjs covers the rule).
  assert.match(page, /replaceCodingWorkItemUrl\(addressSelectionAfterRead\(\{\s*asked: preferredSelectedId \|\| selectedWorkItemIdFromUrl\(\), shown: nextSelectedId \}\)\)/);
  // Arriving on Sessions does not write the shown session.
  assert.doesNotMatch(page, /activeNav === "sessions" && selectedId && selectedWorkItemIdFromUrl\(\) !== selectedId/);
});
