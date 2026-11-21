import assert from "node:assert/strict";
import { test } from "node:test";
import { isExplicitAgentLaunch } from "../../src/chat/agentLaunch.ts";

test("a new chat opened for a selectable agent makes that agent the explicit choice", () => {
  assert.equal(isExplicitAgentLaunch("?new=true&agent_id=a1&project_id=p&workspace_id=p", true, "a1", ["a1", "a2"]), true);
});

test("a workspace default agent, an inactive agent or an existing session is never an explicit launch", () => {
  assert.equal(isExplicitAgentLaunch("?new=true", true, "a1", ["a1"]), false);
  assert.equal(isExplicitAgentLaunch("?new=true&agent_id=a3", true, "a3", ["a1"]), false);
  assert.equal(isExplicitAgentLaunch("?new=true&agent_id=a1", true, "a2", ["a1", "a2"]), false);
  assert.equal(isExplicitAgentLaunch("?session_id=s&agent_id=a1", false, "a1", ["a1"]), false);
});
