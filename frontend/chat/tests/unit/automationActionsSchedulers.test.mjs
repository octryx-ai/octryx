// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/automationActionsSchedulers.test.mjs
//
// An Action card says what starts it.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

import { actionTypeLabel, startedByLine, startedByShort } from "../../src/admin/components/automation/actionStartedBy.ts";

test("what starts an action reads in words", () => {
  assert.equal(startedByLine({ started_by: [] }), "Started only with Run now");
  assert.equal(startedByLine({ managed_by_work: true }), "Started by Work → Intake (managed there)");
  assert.equal(
    startedByLine({ started_by: [
      { kind: "scheduler", name: "Morning digest", when: "Weekdays at 08:00", active: "yes" },
      { kind: "webhook", name: "Alerts", when: "When an alert arrives", active: "no" },
    ] }),
    "Started by schedule Morning digest (Weekdays at 08:00), webhook Alerts (When an alert arrives, paused)",
  );
});

test("the Actions table says what starts an action and its type in a few readable words", () => {
  assert.equal(startedByShort({ started_by: [] }), "Run now only");
  assert.equal(startedByShort({ managed_by_work: true }), "Work › Intake");
  assert.equal(startedByShort({ started_by: [
    { kind: "webhook", name: "Kubernetes alert", when: "When an alert arrives", active: "no" },
    { kind: "scheduler", name: "Morning digest", when: "Weekdays at 08:00", active: "yes" },
  ] }), "Webhook · Kubernetes alert (paused) +1");
  assert.equal(actionTypeLabel("agent_run"), "Agent run");
  assert.equal(actionTypeLabel("secure_work_jira_sync"), "Jira intake sync");
  assert.equal(actionTypeLabel("secure_work_servicenow_sync"), "ServiceNow intake sync");
  assert.equal(actionTypeLabel("secure_work_github_sync"), "Work github sync");
  assert.equal(actionTypeLabel(""), "—");
});

test("The outbound catalog lists only emitted events and Channels reach the Voice settings", async () => {
  const { OUTBOUND_WEBHOOK_EVENT_OPTIONS } = await import("../../src/admin/types/adminPanelTypes.governance.ts");
  assert.ok(!OUTBOUND_WEBHOOK_EVENT_OPTIONS.includes("knowledge.updated"));
  assert.ok(OUTBOUND_WEBHOOK_EVENT_OPTIONS.includes("worker.monitor.alert"));
  assert.ok(OUTBOUND_WEBHOOK_EVENT_OPTIONS.includes("problem.raised"));
  assert.ok(OUTBOUND_WEBHOOK_EVENT_OPTIONS.includes("problem.cleared"));
  const tabs = fs.readFileSync(new URL("../../src/admin/components/AdminChannelSectionTabs.tsx", import.meta.url), "utf8");
  assert.match(tabs, /\{ id: "voice", label: "Voice calls" \}/);
  const deliveries = fs.readFileSync(new URL("../../src/admin/components/AdminOutboundDeliverySection.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(deliveries, /webhook_id\.slice/);
});

test("a scheduler is created in the side panel, never in an inline row on the list", () => {
  const schedulers = ["AdminSchedulersTab.tsx", "scheduler/SchedulerFormPanel.tsx", "scheduler/SchedulerDetailPanel.tsx", "scheduler/schedulerRowWords.tsx"]
    .map((file) => fs.readFileSync(new URL(`../../src/admin/components/${file}`, import.meta.url), "utf8")).join("\n");
  assert.doesNotMatch(schedulers, /placeholder="e\.g\./, "no example values in placeholders");
  assert.doesNotMatch(schedulers, /SchedulerInlineCreate/);
  assert.match(schedulers, /<SidePanel/);
});
