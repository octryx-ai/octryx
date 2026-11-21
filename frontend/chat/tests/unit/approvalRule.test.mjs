// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/approvalRule.test.mjs
//
// The platform approval rule (Settings → Governance → "Approval rule"): the model fails closed to four-eyes, and the
// settings page saves the chosen rule. Requests are stubs.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  approvalModeBadgeText, approvalModeHistoryText, readApprovalRule,
} from "../../src/admin/components/approvalRule/approvalRule.ts";
import { act, byTestId, click, load, server, text, tick } from "./policyEngineHarness.mjs";

const OPTIONS = [{ value: "four_eyes", label: "Four-eyes (a second admin approves)" },
  { value: "single_admin", label: "Single admin may approve own changes" }];
const ANSWER = (rule) => ({ rule, label: OPTIONS.find((item) => item.value === rule).label, options: OPTIONS,
  self_approval_allowed: rule === "single_admin", self_approval_source: rule === "single_admin" ? "approval_rule" : null });

test("model: an unknown or missing answer reads as four-eyes; the badge and history texts follow the rule", () => {
  assert.deepEqual([readApprovalRule(null).rule, readApprovalRule({ rule: "nobody" }).selfApprovalAllowed], ["four_eyes", false]);
  const single = readApprovalRule(ANSWER("single_admin"));
  assert.equal(approvalModeBadgeText(single), "Single admin: self-approval on");
  assert.equal(approvalModeBadgeText(readApprovalRule(ANSWER("four_eyes"))), "Four-eyes approval");
  assert.deepEqual([approvalModeHistoryText("self"), approvalModeHistoryText("four_eyes")], ["self-approved", null]);
});

test("page: an admin switches the rule; a non-admin cannot", async () => {
  const srv = server((call) => (call.method === "PUT"
    ? { status: 200, body: ANSWER(call.body.rule) } : { status: 200, body: ANSWER("four_eyes") }));
  const { AdminApprovalRule } = load("admin/components/approvalRule/AdminApprovalRule.tsx", { fetch: srv.fetch, window: undefined });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminApprovalRule, { isAdmin: true })); });
  await tick();
  assert.equal(byTestId(view, "approval-rule-four_eyes")[0].props.checked, true, "new installs start with four-eyes");
  assert.equal(byTestId(view, "approval-rule-save")[0].props.disabled, true);
  await act(async () => { byTestId(view, "approval-rule-single_admin")[0].props.onChange(); });
  await click(view, "approval-rule-save");
  await tick();
  assert.deepEqual(srv.calls.find((call) => call.method === "PUT").body, { rule: "single_admin" });
  assert.equal(text(byTestId(view, "approval-rule-message")[0]), "Approval rule saved: Single admin may approve own changes.");

  let readOnly;
  await act(async () => { readOnly = TestRenderer.create(createElement(AdminApprovalRule, { isAdmin: false })); });
  await tick();
  assert.equal(byTestId(readOnly, "approval-rule-save")[0].props.disabled, true);
});
