// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/triageRouting.test.mjs
//
// Routing by type after the triage (spec B/C §1): the Workspace's routes are read as the effective
// rows (a switched-off type reads "No follow-up"), saved as only what differs from the defaults (a removed default
// type is switched off), and the run start asks for the Work item's entry workflow to preselect it.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  NO_FOLLOW_UP,
  readTriageRouting,
  triageRoutingError,
  triageRoutingPath,
  triageRoutingPayload,
} from "../../src/chat/work/intake/triageRoutingModel.ts";
import { startableWorkflowsPath } from "../../src/chat/workflowRun/workflowRunRequests.ts";

const DEFAULTS = { feature: "epic-delivery", bug: "bug-fix-reproduction", incident: "incident-analysis" };

test("the effective routes become rows; a switched-off type reads No follow-up", () => {
  const read = readTriageRouting({ routes: { bug: null }, defaults: DEFAULTS, can_edit: false,
    effective: { ...DEFAULTS, bug: null } });
  assert.deepEqual(read.rows, [
    { type: "feature", workflowKey: "epic-delivery" },
    { type: "bug", workflowKey: NO_FOLLOW_UP },
    { type: "incident", workflowKey: "incident-analysis" },
  ]);
  assert.equal(read.canEdit, false);
  assert.equal(readTriageRouting({ workflows: [] }), null);
  assert.equal(triageRoutingPath("ws 1"), "/api/v1/workflow-runs/triage-routing?project_id=ws%201");
});

test("only the differences from the defaults are saved; a removed default type is switched off", () => {
  const rows = [
    { type: "feature", workflowKey: "epic-delivery" },
    { type: "bug", workflowKey: "pr-fix" },
    { type: "Security", workflowKey: "incident-analysis" },
  ];
  assert.deepEqual(triageRoutingPayload(rows, DEFAULTS), {
    routes: { bug: "pr-fix", security: "incident-analysis", incident: null },
  });
  assert.equal(triageRoutingError(rows), null);
  assert.match(triageRoutingError([...rows, { type: "bug", workflowKey: "" }]), /once/);
  assert.match(triageRoutingError([{ type: "two words", workflowKey: "" }]), /lower case/);
  assert.match(triageRoutingError([{ type: "task", workflowKey: "jira-intake-triage" }]), /triage/);
});

test("the run start asks for the Work item's entry workflow", () => {
  assert.equal(startableWorkflowsPath("ws1", "item 1"),
    "/api/v1/workflow-runs/startable?project_id=ws1&work_item_id=item+1");
  assert.equal(startableWorkflowsPath(null), "/api/v1/workflow-runs/startable");
  assert.equal(startableWorkflowsPath("ws1"), "/api/v1/workflow-runs/startable?project_id=ws1");
});
