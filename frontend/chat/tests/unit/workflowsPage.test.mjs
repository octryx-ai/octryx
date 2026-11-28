// Agents & workflows → Workflows (A5): the overview rows, their status and the check results (A6).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  WORKFLOWS_OVERVIEW_PATH,
  failedCheckLabel,
  readCheckResults,
  readWorkflowsOverview,
  statusLabel,
} from "../../src/admin/components/agentsWorkflows/workflows/workflowsModel.ts";
import { parseTurnWorkflowChecks, presentWorkflowChecks } from "../../src/chat/run/turnWorkflowChecks.ts";

const RAW = {
  usage_window_days: 14,
  flows: [
    {
      flow_id: "f1", key: "answer-from-docs", title: "Answer from documents", capability_class: "read_only", node_count: 4,
      execution_kind: "phased", scope: "Global", project_id: null, used: 7, status: "published", version: 3,
    },
    { flow_id: "f2", key: "draw-it", title: "Diagram", node_count: 2, scope: "Claims", project_id: "ws", status: "draft", version: 1 },
  ],
};

test("the overview comes from the phased workflows and reads only flows", () => {
  assert.equal(WORKFLOWS_OVERVIEW_PATH, "/api/v1/phased-workflows/overview");
  const { flows, usageWindowDays } = readWorkflowsOverview(RAW);
  assert.equal(usageWindowDays, 14);
  assert.deepEqual(flows.map((row) => row.key), ["answer-from-docs", "draw-it"]);
  assert.equal(statusLabel(flows[0]), "Published v3");
  assert.equal(statusLabel(flows[1]), "Draft v1");
  assert.equal(readWorkflowsOverview({}).usageWindowDays, 30);
  assert.deepEqual(Object.keys(readWorkflowsOverview(RAW)).sort(), ["flows", "usageWindowDays"]);
});

test("check results read closed rows and name the first failed blocking check", () => {
  const [row] = readCheckResults({
    results: [{
      id: "r1", session_id: "s1", workflow_key: "answer-from-docs", runtime: "octryx_claude", state: "stop_blocked",
      results: [
        { type: "answer_contains_any", outcome: "failed", blocking: false, description: "Mentions the release" },
        { type: "tool_called", outcome: "failed", blocking: true, description: "Evidence retrieved" },
      ],
    }],
  });
  assert.equal(row.runtime, "octryx_claude");
  assert.equal(failedCheckLabel(row), "Evidence retrieved");
  assert.equal(readCheckResults({}).length, 0);
});

test("the turn card shows checks passed or not verified; reminded and unknown render nothing", () => {
  const notVerified = parseTurnWorkflowChecks({
    workflow_key: "answer-from-docs", state: "not_verified",
    results: [{ type: "citations_present", outcome: "failed", blocking: true, description: "Sources cited" }],
  });
  assert.equal(presentWorkflowChecks(notVerified).label, "not verified");
  assert.match(presentWorkflowChecks(notVerified).description, /Sources cited/);
  assert.equal(presentWorkflowChecks(parseTurnWorkflowChecks({ state: "passed", results: [] })).tone, "success");
  assert.equal(presentWorkflowChecks(parseTurnWorkflowChecks({ state: "reminded" })), null);
  assert.equal(parseTurnWorkflowChecks({ state: "green" }), null);
});
