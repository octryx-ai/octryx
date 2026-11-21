import assert from "node:assert/strict";
import { test } from "node:test";
import {
  INITIAL_SOURCE_LIMIT,
  REMOVE_SOURCE_CONSEQUENCES,
  isRemovedSource,
  mayOpenOriginal,
  originalActionLabel,
  removedNotice,
  revisionLabel,
  revisionSummary,
  sourceListingSummary,
  sourceRow,
} from "../../src/chat/knowledge/sourceInventoryModel.ts";
import { originalContentUrl } from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeRequest.ts";
import { matchedIds } from "../../src/admin/components/entityGraph/entityGraphMatches.ts";

test("every page says whether older sources exist; the filter runs on the server (J-C-001)", () => {
  assert.equal(INITIAL_SOURCE_LIMIT, 50);
  assert.equal(sourceListingSummary(50, true, ""), "Showing the newest 50 documents; load more to see older ones.");
  assert.equal(sourceListingSummary(3, false, ""), "Showing all 3 documents.");
  assert.equal(sourceListingSummary(2, false, "guide"), "Showing all 2 documents matching “guide”.");
  assert.equal(sourceListingSummary(0, false, "x"), "No document title or key matches “x”.");
  assert.equal(sourceListingSummary(0, false, ""), "No documents in this workspace yet.");
});

test("originals open for every revision except removed ones", () => {
  assert.equal(mayOpenOriginal("projected"), true);
  assert.equal(mayOpenOriginal("superseded"), true);
  assert.equal(mayOpenOriginal("tombstoned"), false);
  assert.equal(revisionLabel("registered"), "Received, not indexed yet");
  assert.equal(originalActionLabel("application/pdf"), "Open original");
  assert.equal(originalActionLabel("text/csv"), "Download original");
});

test("one compact Revisions cell says the count and, when it adds something, the latest ordinal", () => {
  assert.equal(revisionSummary(1, 1), "1 revision");
  assert.equal(revisionSummary(3, 3), "3 revisions · latest #3");
  assert.equal(revisionSummary(1, 2), "1 revision · latest #2");
  assert.equal(revisionSummary(2, null), "2 revisions");
  assert.equal(revisionSummary(0, null), "No revisions");
});

test("a row is title first with the technical key as secondary text", () => {
  const source = { source_id: "s1", source_key: "spring-boot-4-0-configuration-changelog-3",
    display_title: "Spring Boot 4.0 Configuration Changelog", revision_count: 1, latest_revision_ordinal: 1 };
  assert.deepEqual(sourceRow(source), { id: "s1", title: "Spring Boot 4.0 Configuration Changelog",
    key: "spring-boot-4-0-configuration-changelog-3", revisions: "1 revision" });
  assert.equal(sourceRow({ ...source, display_title: "  " }).title, "spring-boot-4-0-configuration-changelog-3");
});

test("removal is described as the backend tombstone does it, not as an erase", () => {
  assert.deepEqual(REMOVE_SOURCE_CONSEQUENCES, [
    "The document leaves this workspace's searchable knowledge.",
    "Its history stays in the evidence ledger.",
    "Uploading the same file again brings it back.",
  ]);
  assert.equal(removedNotice("Guide"), "“Guide” was removed from this workspace's searchable knowledge.");
  const revision = (state) => ({ revision_id: state, state });
  assert.equal(isRemovedSource({ revisions: [revision("tombstoned")] }), true);
  assert.equal(isRemovedSource({ revisions: [revision("tombstoned"), revision("projected")] }), false);
  assert.equal(isRemovedSource({ revisions: [] }), false);
  assert.equal(isRemovedSource(null), false);
});

test("the original URL is workspace-scoped and encodes every segment", () => {
  assert.equal(
    originalContentUrl("ws 1", "src/2", "rev?3"),
    "/api/v1/workspaces/ws%201/knowledge/sources/src%2F2/revisions/rev%3F3/original",
  );
});

test("graph search reads the matched entity ids", () => {
  const nodes = [{ id: "a", matched: true }, { id: "b", matched: false }, { id: "c", matched: false }];
  const payload = { nodes, match_ids: ["a"], stats: { matched_nodes: 1, match_limit: 100 } };
  assert.deepEqual([...matchedIds(payload)], ["a"]);
});

test("a document row says where it comes from, never its internal key", async () => {
  const { documentOriginLine } = await import("../../src/chat/knowledge/syncedSourceModel.ts");
  const synced = (kind) => ({ origin: { type: "connector", connector_kind: kind, connector_key: "servicenow-acme-orders", url: null } });
  assert.equal(documentOriginLine(synced("servicenow")), "From ServiceNow");
  assert.equal(documentOriginLine(synced("confluence")), "From Confluence");
  assert.equal(documentOriginLine({ origin: { type: "upload" } }), "Uploaded");
  assert.equal(documentOriginLine({}), "Uploaded");
});
