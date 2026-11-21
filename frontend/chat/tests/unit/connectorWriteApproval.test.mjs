// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/connectorWriteApproval.test.mjs
// A chat's connector write is confirmed per call. The card reads the gate's preview (tool, connector,
// connection, every written field as "key: value") into what is written, where, and the field list.
import assert from "node:assert/strict";
import { test } from "node:test";

import { connectorWriteStatus, connectorWriteView } from "../../src/chat/approval/connectorWriteView.ts";

// The payload shape of backend/app/services/tool_approval_gate.py `_chat_write_preview` (test_chat_connector_writes).
const PREVIEW = {
  kind: "tool_execution",
  title: "Execute tool create_jira_ticket",
  summary: "Writes through a connection from a chat.",
  toolName: "create_jira_ticket",
  standing_rule: null,
  connection: "Jira",
  details: [
    "tool: create_jira_ticket",
    "connector: jira",
    "connection: Jira",
    "project_key: CHEF",
    "issue_type: Epic",
    "summary: Kitchen helper v1",
    "description: Kitchen helper v1 as a local web app.\nSecond line: kept.",
    'labels: ["kitchen-helper","v1"]',
    "project_key: CHEF",
  ],
};

test("a chat connector write reads as what is written, where, and every field once, in order", () => {
  const view = connectorWriteView(PREVIEW, null);
  assert.equal(view.action, "Create Jira ticket");
  assert.equal(connectorWriteView({ ...PREVIEW, title: undefined }, null).title, "Create Jira ticket", "no title: the action");
  assert.equal(view.connector, "Jira");
  assert.equal(view.connection, "Jira");
  assert.deepEqual(view.fields.map((field) => [field.label, field.value]), [
    ["Project key", "CHEF"],
    ["Issue type", "Epic"],
    ["Summary", "Kitchen helper v1"],
    ["Description", "Kitchen helper v1 as a local web app.\nSecond line: kept."],
    ["Labels", "kitchen-helper, v1"],
  ]);
});

test("the tool's own preview title wins over the action name", () => {
  const view = connectorWriteView({ ...PREVIEW, title: "Create Epic Kitchen helper v1 in CHEF" }, null);
  assert.equal(view.title, "Create Epic Kitchen helper v1 in CHEF");
});

test("other approvals keep their own card", () => {
  assert.equal(connectorWriteView({ kind: "tool_execution", title: "Execute tool shell", details: ["command: ls"] }, "shell"), null);
  assert.equal(connectorWriteView(null, null), null);
});

test("only a pending write asks for attention; decided ones say how they ended", () => {
  assert.deepEqual(connectorWriteStatus("pending"), { label: "Waiting for you", tone: "attention" });
  assert.deepEqual(connectorWriteStatus("approved"), { label: "Approved", tone: "success" });
  assert.deepEqual(connectorWriteStatus("rejected"), { label: "Rejected", tone: "problem" });
});
