// The composer's workflow chip (A9): the selected workflow's class and its steps with their mode.
import assert from "node:assert/strict";
import { test } from "node:test";
import { workflowClass, workflowClassLabel, workflowStepsText } from "../../src/chat/composer/workflowClass.ts";

test("the declared class wins; a Diagnosis/Change capability maps onto a class", () => {
  assert.equal(workflowClass({ capability: "change", capability_class: "deliver" }), "deliver");
  assert.equal(workflowClass({ capability: "diagnosis", capability_class: null }), "read_only");
  assert.equal(workflowClass({ capability: "", capability_class: "unknown" }), "");
  assert.equal(workflowClass(undefined), "");
  assert.equal(workflowClassLabel("read_only"), "Read-only");
});

test("steps read in order with their strict or guided mode", () => {
  const option = { steps: [
    { tool: "knowledge_search", label: "Search sources", required: true, mode: "strict" },
    { tool: "create_diagram", label: "", required: true, mode: "guided" },
  ] };
  assert.equal(workflowStepsText(option), "Steps: 1 Search sources (strict) · 2 create_diagram (guided)");
  assert.equal(workflowStepsText({ steps: [] }), "");
});
