// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/limitsContract.test.mjs
//
// Runtime → Limits & budgets (S5): one table of limits with sources and
// Workspace overrides; only changed keys are saved; an empty value is never saved as "no limit"; budget periods.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  LIMIT_ROWS,
  atLimitText,
  budgetPayload,
  draftsFromSettings,
  emptyBudget,
  isNoLimit,
  limitsPayload,
  overrideCount,
  readOverview,
  usedText,
} from "../../src/admin/components/limits/limitsContract.ts";

const SETTINGS = { agent_session_cost_limit_usd: 25, agent_request_cost_limit_usd: 0, max_output_tokens_default: 4096 };

test("only the changed limits are sent; empty is refused, 0 on a cost cap is the explicit No limit", () => {
  const stored = draftsFromSettings(SETTINGS);
  assert.deepEqual(limitsPayload(stored, stored), { payload: {} });
  assert.deepEqual(limitsPayload({ ...stored, agent_session_cost_limit_usd: "30" }, stored),
    { payload: { agent_session_cost_limit_usd: 30 } });
  assert.match(limitsPayload({ ...stored, agent_session_cost_limit_usd: "" }, stored).error, /No limit/);
  assert.match(limitsPayload({ ...stored, max_output_tokens_default: "4.5" }, stored).error, /whole number/);
  const requestCap = LIMIT_ROWS.find((row) => row.key === "agent_request_cost_limit_usd");
  assert.equal(isNoLimit(requestCap, stored.agent_request_cost_limit_usd), true);
});

test("the overview is read into overrides, environment limits and budgets", () => {
  const overview = readOverview({
    workspace_overrides: { agent_request_cost_limit_usd: [{ workspace_id: "w1", name: "Claims Desk", value: "5" }] },
    gateway_daily_baseline_usd: 50,
    environment_limits: [{ key: "rate_limit_user_read_per_min", label: "Reads per person per minute", value: 3000 }],
    budgets: [{ id: "b1", name: "n", scope: "workspace", scope_label: "Claims Desk", workspace_id: "w1", period: "monthly",
      amount_usd: "800", used_usd: "212", warn_at_percent: 80, block_at_percent: 100, is_active: true }],
  });
  assert.equal(overrideCount(overview, "agent_request_cost_limit_usd"), 1);
  assert.equal(overview.environment[0].value, "3000");
  assert.equal(usedText(overview.budgets[0]), "$212.00 (27%)");
  assert.equal(atLimitText(overview.budgets[0]), "Stop");
});

test("a budget needs a scope target, an amount above zero and ordered percentages", () => {
  const names = { workspaces: [{ id: "w1", name: "Claims Desk" }], users: [] };
  assert.match(budgetPayload(emptyBudget(), names).error, /Workspace/);
  assert.match(budgetPayload({ ...emptyBudget(), targetId: "w1", amount: "0" }, names).error, /above zero/);
  assert.match(budgetPayload({ ...emptyBudget(), targetId: "w1", amount: "10", warnAt: "90", stopAt: "80" }, names).error,
    /stop at/);
  assert.deepEqual(budgetPayload({ ...emptyBudget(), targetId: "w1", amount: "800" }, names).payload, {
    name: "Claims Desk · Month", project_id: "w1", reset_period: "monthly", monthly_cost_limit: 800,
    warn_at_percent: 80, block_at_percent: 100, is_active: true,
  });
});
