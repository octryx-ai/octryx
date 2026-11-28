import assert from "node:assert/strict";
import { test } from "node:test";
import { flowEditorHref } from "../../src/admin/editorLinks.ts";
import { readOpenWorkflow } from "../../src/admin/components/agentsWorkflows/workflows/workflowListModel.ts";

test("a workflow link opens that workflow in the Workflows designer", () => {
  const link = new URL(flowEditorHref("7784cd96 x"), "http://x");
  assert.equal(link.searchParams.get("area"), "workflows");
  assert.equal(link.searchParams.get("tab"), "workflowDesigner");
  assert.equal(link.searchParams.get("view"), "canvas");
  assert.equal(readOpenWorkflow(link.search), "7784cd96 x");
  assert.equal(readOpenWorkflow("?tab=workflowList"), null);
});
