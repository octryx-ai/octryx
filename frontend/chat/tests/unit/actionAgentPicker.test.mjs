// The Reviewer is never offered for an Action.
import assert from "node:assert/strict";
import { test } from "node:test";
import { compatibleAgents } from "../../src/admin/components/automation/actionGuidedPath.ts";

test("the Action agent picker never offers the Reviewer", () => {
  const agents = [
    { id: "1", name: "Assistant", isActive: true, projectId: "", builtinKey: "assistant" },
    { id: "2", name: "Engineer", isActive: true, projectId: "", builtinKey: "engineer" },
    { id: "3", name: "Reviewer", isActive: true, projectId: "", builtinKey: "reviewer" },
  ];
  assert.deepEqual(compatibleAgents(agents, "ws").map((agent) => agent.name), ["Assistant", "Engineer"]);
});
