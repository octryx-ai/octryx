import assert from "node:assert/strict";
import { test } from "node:test";
import { flowEditorHref, readFlowIdFromSearch } from "../../src/admin/editorLinks.ts";

test("editor links name only the target; each editor reads its own parameter", () => {
  const flow = new URL(flowEditorHref("7784cd96 x"), "http://x");
  // One concept Workflow: a flow opens in the Workflows page's Canvas view.
  assert.equal(flow.searchParams.get("tab"), "workflowList");
  assert.equal(flow.searchParams.get("view"), "canvas");
  assert.equal(readFlowIdFromSearch(flow.search), "7784cd96 x");
  assert.equal(readFlowIdFromSearch("?tab=workflowList"), "");
});
