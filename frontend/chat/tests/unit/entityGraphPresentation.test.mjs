import assert from "node:assert/strict";
import { test } from "node:test";
import { graphDestination, graphExplorerUrl, graphNotice } from "../../src/admin/components/entityGraph/entityGraphPresentation.ts";
import { assignTypeSlots, slotColor } from "../../src/admin/components/entityGraph/kgView.ts";

const payload = (state, nodes=[]) => ({state,nodes});
test("current graph calls are workspace required and query values cannot escape scope", () => {
  assert.throws(()=>graphExplorerUrl("", "", "", 150), /Choose a workspace/);
  const url = new URL(graphExplorerUrl("workspace/a", "a&project_id=other", "node/b", 80), "https://local.test");
  assert.equal(url.pathname, "/api/v1/workspaces/workspace%2Fa/knowledge/graph/explorer");
  assert.equal(url.searchParams.get("query"), "a&project_id=other");
  assert.equal(url.searchParams.get("project_id"), null);
  assert.equal(url.searchParams.get("focus_node_id"), "node/b");
});
test("configuration failures and store errors never become successful empty graphs", () => {
  assert.match(graphNotice(payload("needs_configuration"),0,"").title, /configuration/);
  for(const state of ["unavailable","unauthorized","timeout","contract_violation"]) {
    assert.match(graphNotice(payload(state),0,"").title, /could not be loaded/);
  }
  assert.match(graphNotice(payload("unexpected"),0,"").title, /not recognized/);
});
test("no matches, no extraction and hidden filters have distinct recoverable states", () => {
  assert.equal(graphNotice(payload("no_matches"),0,"needle").reset, true);
  assert.match(graphNotice(payload("no_matches"),0,"needle").text, /needle/);
  assert.equal(graphNotice(payload("not_extracted"),0,"").reset, false);
  assert.equal(graphNotice(payload("ok",[{id:"a"}]),0,"").title, "All entities are hidden");
  assert.equal(graphNotice(payload("ok",[{id:"a"}]),1,""), null);
  assert.equal(graphNotice(null,0,""), null);
});
test("empty view destinations retain workspace and distinguish documents from code", () => {
  const docs = new URL(graphDestination("workspace-a", "documents"), "https://local.test");
  assert.equal(docs.searchParams.get("tab"), "knowledgeSources");
  assert.equal(docs.searchParams.get("workspace_id"), "workspace-a");
  const repos = new URL(graphDestination("workspace-a", "repositories"), "https://local.test");
  assert.equal(repos.searchParams.get("coding_view"), "repositories");
  assert.equal(repos.searchParams.get("workspace_id"), "workspace-a");
});
test("entity types use the graph's type colour variables rather than status colors", () => {
  const slots = assignTypeSlots({ person: 3, repository: 2, entity: 1, unknown: 1 });
  for(const type of ["person","repository","entity","unknown"]) assert.match(slotColor(slots.get(type)), /^var\(--kg-type-/);
});

test("empty default results do not offer a no-op reset, while empty focused neighborhoods do", () => {
  assert.equal(graphNotice(payload("no_matches"),0,"").reset, false);
  assert.equal(graphNotice(payload("no_matches"),0,"","selected-node").reset, true);
});


test("unextracted graph guides source preparation and the real admin extraction path", () => {
  const notice = graphNotice(payload("not_extracted"), 0, "");
  assert.match(notice.text, /Check source processing, product and version in Documents/);
  assert.match(notice.text, /Uploading alone does not create the graph/);
  assert.match(notice.text, /Admin › Knowledge › Changes/);
  assert.match(notice.text, /knowledge authoring access/);
  assert.match(notice.text, /ask your workspace owner/);
  assert.equal(notice.reset, false);
});
