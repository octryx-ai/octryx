// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// W28 (W27 follow-ups): "Always for this Workspace" on a tool approval is shown
// only to Workspace admins/owners; the agent's plan is a read-only inline view
// model; the admin editors read the settings record and revoke standing tool
// approvals.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  approvalCardModel,
  standingRuleScopeLabel,
} from "../../src/chat/approvalCardActions.ts";
import { PLAN_MAX_STEPS, planStepMarker, turnPlanFromToolEvents } from "../../src/chat/turnPlan.ts";
import {
  parsePolicyListRefusal,
  parsePolicyListState,
  settingsToText,
  textToSettings,
} from "../../src/admin/components/policyLists.ts";
import {
  revokeStandingToolRulePatch,
  standingToolRuleLabel,
  standingToolRules,
} from "../../src/admin/components/projectsTab/standingToolApprovals.ts";

const kinds = (model) => model.actions.map((action) => action.kind);

test("Always for this Workspace is visible only with the grant permission", () => {
  const tool = {
    id: "a1",
    status: "pending",
    action: "Approve tool execution for run_cli_command",
    standingRule: { toolName: "run_cli_command", argumentClass: "git status" },
    changePreview: { id: "p1", preview: { offered_decisions: ["once", "always", "deny"] } },
  };
  assert.deepEqual(kinds(approvalCardModel(tool, { canRetry: false, canGrantStandingConfirmation: true })), [
    "reject",
    "always",
    "approve",
  ]);
  assert.deepEqual(kinds(approvalCardModel(tool, { canRetry: false, canGrantStandingConfirmation: false })), [
    "reject",
    "approve",
  ]);
  // No server-named scope (a compound command, a content check): the server does not offer it.
  assert.deepEqual(
    kinds(approvalCardModel({ ...tool, standingRule: null, changePreview: { id: "p1", preview: { offered_decisions: ["once", "deny"] } } },
      { canRetry: false, canGrantStandingConfirmation: true })),
    ["reject", "approve"],
  );
  assert.deepEqual(
    kinds(approvalCardModel({ ...tool, status: "approved" }, { canRetry: false, canGrantStandingConfirmation: true })),
    [],
  );
  assert.equal(standingRuleScopeLabel(tool.standingRule), "run_cli_command · git status");
  assert.equal(standingRuleScopeLabel({ toolName: "write_file", argumentClass: null }), "write_file");
});

test("the inline plan is the last successful todo_write of the message", () => {
  const event = (todos, extra = {}) => ({
    id: "t",
    toolName: "todo_write",
    parameters: { todos },
    result: { saved: todos.length },
    status: "success",
    createdAt: null,
    ...extra,
  });
  const plan = turnPlanFromToolEvents([
    event([{ id: "1", subject: "Old plan", status: "pending" }]),
    { id: "x", toolName: "read_file", parameters: {}, result: {}, status: "success", createdAt: null },
    event([
      { id: "1", subject: "Read the  failing test", status: "completed" },
      { id: "2", subject: "Fix the validator", status: "in_progress" },
      { id: "3", subject: "Run the suite", status: "made_up" },
      { id: "", subject: "no id" },
    ]),
    event([{ id: "9", subject: "Failed write", status: "pending" }], { status: "error", result: { error: "x" } }),
  ]);
  assert.deepEqual(plan, {
    steps: [
      { id: "1", subject: "Read the failing test", status: "completed" },
      { id: "2", subject: "Fix the validator", status: "in_progress" },
      { id: "3", subject: "Run the suite", status: "pending" },
    ],
    completed: 1,
    total: 3,
    current: "Fix the validator",
    truncated: false,
  });
  assert.equal(turnPlanFromToolEvents([]), null);
  assert.equal(turnPlanFromToolEvents([event([])]), null);
  const long = Array.from({ length: PLAN_MAX_STEPS + 2 }, (_, index) => ({
    id: String(index),
    subject: `Step ${index}`,
    status: "pending",
  }));
  const bounded = turnPlanFromToolEvents([event(long)]);
  assert.equal(bounded.steps.length, PLAN_MAX_STEPS);
  assert.equal(bounded.truncated, true);
  assert.equal(planStepMarker("completed"), "✓");
});

test("the proposal settings record and the standing tool approvals are editable in the admin", () => {
  const state = parsePolicyListState({
    list_id: "workflow_proposal_settings",
    key: "workflow_proposal_settings.v1",
    version: 1,
    values: { timeout_seconds: 10 },
  });
  assert.deepEqual(state.settings, { timeout_seconds: 10 });
  assert.deepEqual(textToSettings(settingsToText(state.settings)), state.settings);
  assert.deepEqual(parsePolicyListRefusal({ detail: { code: "out_of_range", values: ["timeout_seconds"] } }), {
    code: "out_of_range",
    values: ["timeout_seconds"],
    message: "",
  });

  const config = {
    standing_tool_approvals: {
      rules: [
        { tool_name: "run_cli_command", argument_class: "git status", granted_by: "u1", granted_at: "t" },
        { tool_name: "write_file", argument_class: null },
        { argument_class: "broken" },
      ],
    },
  };
  const rules = standingToolRules(config);
  assert.deepEqual(rules.map(standingToolRuleLabel), ["run_cli_command · git status", "write_file"]);
  assert.deepEqual(revokeStandingToolRulePatch(config, rules[0]), {
    standing_tool_approvals: {
      rules: [{ tool_name: "write_file", argument_class: null }, { argument_class: "broken" }],
    },
  });
});
