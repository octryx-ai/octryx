// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/mcpAllowContract.test.mjs
//
// MCP servers allowed per Workspace (S6): the status pipeline, the allow body
// with all or selected tools, the drawer's starting choice and fixed refusal wording.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  allowBody,
  allowErrorText,
  inUse,
  initialTools,
  pipeline,
  readAllow,
  readStatus,
} from "../../src/admin/components/mcpAllow/mcpAllowContract.ts";

test("a connected server allowed nowhere is not usable yet, and the pipeline says why", () => {
  const status = readStatus({ servers: [{ server_id: "s1", name: "Tickets", connected: true, allowed_workspaces: 0,
    tools_visible: false, tool_count: 6 }] }).get("s1");
  assert.equal(inUse(status), false);
  assert.deepEqual(pipeline(status).map((step) => [step.label, step.done]), [
    ["Registered", true], ["Connected", true], ["Not allowed in any Workspace", false], ["Tools visible to agents", false],
  ]);
  assert.equal(pipeline({ ...status, allowedWorkspaces: 1, toolsVisible: true })[2].label, "Allowed in 1 Workspace");
});

test("the allow body carries all tools as null, selected tools sorted, and refuses an empty selection", () => {
  assert.deepEqual(allowBody(["w2", "w1"], true, []).body, { workspace_ids: ["w1", "w2"], tools: null });
  assert.deepEqual(allowBody(["w1"], false, ["b", "a"]).body, { workspace_ids: ["w1"], tools: ["a", "b"] });
  assert.match(allowBody(["w1"], false, []).error, /at least one tool/);
});

test("the drawer starts from the stored selection, and refusals are worded from codes", () => {
  const allow = readAllow({ server_id: "s1", name: "Tickets", connected: true, tools: ["a", "b"],
    workspaces: [{ workspace_id: "w1", name: "Claims", allowed: true, tools: ["a"] }] });
  assert.deepEqual(initialTools(allow), { allTools: false, tools: ["a"] });
  assert.equal(allowErrorText({ detail: { code: "mcp_server_owned_by_another_workspace" } }),
    "Not saved: this server belongs to another Workspace.");
});
