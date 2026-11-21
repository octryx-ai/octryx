import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { approveActionLabel, hasNoDocuments, indexingJobs, researchCounts } from "../../src/chat/knowledge/knowledgeEntryModel.ts";
import { requestDocumentUpload, takeDocumentUploadRequest } from "../../src/chat/knowledge/knowledgeEntryIntent.ts";
import { useKnowledgeEntryOverview } from "../../src/chat/knowledge/useKnowledgeEntryOverview.ts";
import { workspaceScopedHref } from "../../src/chat/knowledge/knowledgeNavigation.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
const source = (id) => ({ source_id: id, source_key: id, display_title: id, revision_count: 1, latest_revision_ordinal: 1 });
const listing = (count, more = false, backlog = {}) =>
  ({ sources: Array.from({ length: count }, (_, i) => source(`s${i}`)), projection_backlog: backlog, next_cursor: more ? "next" : null });
const site = (state) => ({ id: state + Math.random(), state, scope: "workspace", pattern: "docs.spring.io", products: [] });

test("only an empty last page is an empty workspace", () => {
  assert.equal(hasNoDocuments(listing(0)), true);
  assert.equal(hasNoDocuments(listing(0, true)), false);
  assert.equal(hasNoDocuments(listing(7)), false);
  assert.equal(hasNoDocuments(null), false);
});

test("the indexing backlog counts queued and running jobs as waiting, without inventing a state", () => {
  assert.deepEqual(indexingJobs(listing(3, false, { applied: 5, pending: 2, claimed: 1, dead_letter: 1 })), { indexed: 5, waiting: 3, failed: 1 });
  assert.deepEqual(indexingJobs(listing(3, false, { pending: "x", claimed: -2 })), { indexed: 0, waiting: 0, failed: 0 });
  assert.deepEqual(indexingJobs({}), { indexed: 0, waiting: 0, failed: 0 });
});

test("research websites: approved count and the proposals the approve action names", () => {
  const overview = { mode: "trusted_only", sources: [site("trusted"), site("trusted"), site("proposed"), site("blocked")] };
  assert.deepEqual(researchCounts(overview), { approved: 2, proposed: 1 });
  assert.equal(approveActionLabel(overview), "Approve research websites (1)");
  assert.equal(approveActionLabel({ mode: "open", sources: [] }), "Approve research websites");
});

test("upload hand-over opens the Documents drawer once and only for the requesting workspace", () => {
  requestDocumentUpload("workspace-a");
  assert.equal(takeDocumentUploadRequest("workspace-b"), false);
  assert.equal(takeDocumentUploadRequest("workspace-a"), false);
  requestDocumentUpload("workspace-a");
  assert.equal(takeDocumentUploadRequest("workspace-a"), true);
  assert.equal(takeDocumentUploadRequest("workspace-a"), false);
});

test("overview reads each API per workspace; a late answer of the previous workspace is ignored", async () => {
  const pending = [];
  const defer = (kind) => (workspace) => new Promise((resolve, reject) => pending.push({ kind, workspace, resolve, reject }));
  const loaders = { sources: defer("sources"), connectors: defer("connectors"), research: defer("research") };
  let current;
  function Probe({ workspace }) { current = useKnowledgeEntryOverview(workspace, loaders); return null; }
  let view;
  act(() => { view = TestRenderer.create(createElement(Probe, { workspace: "workspace-a" })); });
  act(() => view.update(createElement(Probe, { workspace: "workspace-b" })));
  const find = (kind, workspace) => pending.find((item) => item.kind === kind && item.workspace === workspace);
  await act(async () => find("sources", "workspace-b").resolve(listing(2)));
  await act(async () => find("research", "workspace-b").reject(new Error("forbidden")));
  await act(async () => find("connectors", "workspace-b").resolve({ connectors: [{ connector_key: "c1" }] }));
  await act(async () => find("sources", "workspace-a").resolve(listing(50, true)));
  await act(async () => find("connectors", "workspace-a").reject(new Error("late")));
  assert.equal(current.workspaceId, "workspace-b");
  assert.equal(current.listing.sources.length, 2);
  assert.equal(current.connectors.connectors.length, 1);
  assert.equal(current.connectorsFailed, false);
  assert.equal(current.researchFailed, true);
  assert.equal(current.sourcesFailed, false);
  act(() => view.unmount());
});

test("Knowledge page switches carry the selected workspace", () => {
  const href = "https://octryx.test/chat?area=knowledge&tab=knowledgeLibrary&workspace_id=old";
  const next = new URL(workspaceScopedHref(href, "workspace-a"));
  assert.equal(next.searchParams.get("workspace_id"), "workspace-a");
  assert.equal(next.searchParams.get("tab"), "knowledgeLibrary");
  assert.equal(workspaceScopedHref("https://octryx.test/chat?area=knowledge", ""), "https://octryx.test/chat?area=knowledge");
});
