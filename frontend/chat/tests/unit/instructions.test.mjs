// Agents & workflows → Instructions (A8): rows, labels, filters and conflict findings.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  boundLabel,
  filterInstructions,
  findingText,
  readInstructions,
  scopeLabel,
  statusLabel,
} from "../../src/admin/components/agentsWorkflows/instructions/instructionsModel.ts";

const RAW = {
  items: [
    {
      id: "i1", key: "claims.glossary", title: "Claims glossary", scope_type: "workspace", scope_id: "w1",
      scope_name: "Claims", binding: "always", workflow_key: null, layer: "workspace", layer_budget: 1500,
      status: "active", published: { id: "v1", version: 2, state: "published", token_estimate: 420, findings: [] },
      latest: { id: "v1", version: 2, state: "published", token_estimate: 420, findings: [] },
    },
    {
      id: "i2", key: "release.tone", title: "Release tone", scope_type: "global", scope_id: null, binding: "workflow",
      workflow_key: "release-status", layer: "workflow", status: "active", published: null,
      latest: { id: "v2", version: 1, state: "draft", token_estimate: 260,
                findings: [{ code: "tool_against_capability", names: ["git_push"] }] },
    },
    { id: "i3", key: "x", title: "Weird", scope_type: "nope", binding: "sometimes", status: "active" },
  ],
};

test("rows read with closed scope and binding values and plain labels", () => {
  const [glossary, tone, weird] = readInstructions(RAW);
  assert.equal(scopeLabel(glossary), "Workspace · Claims");
  assert.equal(boundLabel(glossary), "always in Claims");
  assert.equal(scopeLabel(tone), "Workflow");
  assert.equal(boundLabel(tone), "workflow release-status");
  assert.deepEqual(statusLabel(glossary), { label: "Published v2", kind: "active" });
  assert.deepEqual(statusLabel(tone), { label: "Draft v1", kind: "attention" });
  assert.equal(weird.scopeType, "global");
  assert.equal(weird.binding, "always");
  assert.equal(boundLabel({ binding: "on_request", workflowKey: null, scopeName: "", scopeType: "global" }), "on request (by key)");
});

test("search and the scope filter narrow the list; workflow means bound to a workflow", () => {
  const rows = readInstructions(RAW);
  assert.deepEqual(filterInstructions(rows, "release", "").map((row) => row.key), ["release.tone"]);
  assert.deepEqual(filterInstructions(rows, "", "workflow").map((row) => row.key), ["release.tone"]);
  assert.deepEqual(filterInstructions(rows, "", "workspace").map((row) => row.key), ["claims.glossary"]);
});

test("each closed finding reads as one sentence naming what triggered it", () => {
  assert.match(findingText({ code: "tool_against_capability", names: ["git_push"] }), /git_push/);
  assert.match(findingText({ code: "over_budget", names: ["workflow"], tokens: 1800, budget: 1500 }), /1800 of 1500/);
  assert.match(findingText({ code: "something_new", names: ["a"] }), /something_new: a/);
  const forbidden = readInstructions({ items: [{ id: "x", key: "k", latest: { id: "v", findings: [
    { code: "tool_forbidden_by_policy", names: ["web_search"], policy: "Cedar policy no-web-search", detail: "forbid (...)" },
  ] } }] })[0].latest.findings[0];
  assert.equal(forbidden.detail, "forbid (...)");
  assert.match(findingText(forbidden), /web_search.*Cedar policy no-web-search/);
});
