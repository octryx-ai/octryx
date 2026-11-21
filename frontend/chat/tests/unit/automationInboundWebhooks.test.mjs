// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/automationInboundWebhooks.test.mjs
//
// Webhooks → Inbound shows each webhook as a table row (source logo, action, result destination, state in
// words), the latest alerts with their outcome, and a short create form that reveals the URL and the secret once.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { makeLoader, text } from "./automationTestLoader.mjs";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { cannotSignTimestamp, outcomeLabel, stateLine, timestampFixedReason, weekLine } from "../../src/admin/components/inboundWebhooks/inboundWebhookModel.ts";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const HOOK = {
  id: "w1", name: "Alerts – Ops", project_id: "p1", workspace_name: "Ops", source_type: "alertmanager",
  source_label: "Alertmanager", polled: false, is_active: true, has_secret: true, trigger_path: "/api/v1/webhooks/w1/trigger",
  task_id: "t1", action: { id: "t1", name: "Incident analysis", workflow: "read_only" },
  result_to: { kind: "run_history", label: "Run history only" }, state: "active", setup_gap: null, setup_message: "",
  alert_filter: "critical_warning", group_window_minutes: 30, rate_limit_per_hour: 20,
  week: { alerts: 9, grouped: 3, started: 6 }, last_event: null,
};
const EVENT = { id: "e1", webhook_id: "w1", webhook_name: "Alerts – Ops", source_type: "alertmanager",
  received_at: new Date().toISOString(), outcome: "grouped", title: "HighErrorRate · api", message: "Grouped with an earlier alert",
  error: "", is_test: false, task_run_id: "r1", session_id: null };
const SOURCES = [{ key: "alertmanager", label: "Alertmanager", polled: false, samples: [{ key: "firing_error_rate", label: "Firing" }] },
  { key: "jira_change", label: "Jira change", polled: true, samples: [] }];

test("the state reads in words; a webhook without a workflow says what is missing", () => {
  assert.deepEqual(stateLine({ ...HOOK, last_event: EVENT }), { text: "Active", tone: "ok" });
  assert.equal(stateLine({ ...HOOK, state: "needs_setup", setup_message: "The action has no workflow." }).text,
    "Needs setup · The action has no workflow.");
  assert.equal(weekLine(HOOK), "9 alerts this week · 3 grouped as repeats");
});

test("webhook rows, latest alerts and the create form that shows the secret once", async () => {
  const calls = [];
  const readJson = async (url, init) => {
    calls.push([init?.method ?? "GET", url, init?.body ? JSON.parse(init.body) : null]);
    if (url === "/admin/chat/api/panel/webhooks" && init?.method === "POST") return { ...HOOK, id: "w2", name: "New", trigger_path: "/api/v1/webhooks/w2/trigger", secret: "s3cr3t" };
    if (url === "/admin/chat/api/panel/webhooks") return [HOOK];
    if (url.endsWith("/catalog")) return { sources: SOURCES };
    if (url === "/admin/chat/api/panel/tasks") return [{ id: "t1", name: "Incident analysis", project_id: "p1" }];
    if (url.startsWith("/admin/chat/api/panel/webhook-events")) return [EVENT];
    return [];
  };
  const { InboundWebhooksPage } = makeLoader({ "/AutomationIcon": { AutomationIcon: () => null } })("admin/components/inboundWebhooks/InboundWebhooksPage.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(InboundWebhooksPage, { projects: [{ id: "p1", name: "Ops" }], readJson }));
  });
  const all = text(view.root);
  // One table row per webhook; the state is a label whose tooltip is the sentence.
  assert.ok(view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === "w1"));
  assert.match(all, /Incident analysis → Run history only/);
  const state = view.root.find((node) => typeof node.type === "string" && node.props["data-testid"] === "inbound-state-w1");
  assert.deepEqual([text(state), state.props.title], ["Active", "Active · waiting for the first alert"]);
  assert.match(all, /HighErrorRate · api/);
  assert.match(all, /Grouped with an earlier alert/);
  assert.match(all, /Grouped/, "the outcome reads in words");

  const button = (label) => view.root.find((node) => node.type === "button" && text(node).trim().startsWith(label));
  await act(async () => { button("New webhook").props.onClick(); });
  const inputs = () => view.root.findAll((node) => node.type === "input" || node.type === "select");
  await act(async () => { inputs()[0].props.onChange({ target: { value: "New" } }); });
  await act(async () => { inputs()[1].props.onChange({ target: { value: "p1" } }); });
  await act(async () => { inputs()[2].props.onChange({ target: { value: "t1" } }); });
  await act(async () => { button("Create webhook").props.onClick(); });
  const post = calls.find(([method]) => method === "POST");
  assert.deepEqual(post[2], { name: "New", project_id: "p1", source_type: "alertmanager", task_id: "t1",
    accept_untimestamped: true }, "Alertmanager can't sign a timestamp: the explicit setting starts on");
  const secret = view.root.find((node) => node.props?.["data-testid"] === "inbound-secret");
  assert.equal(text(secret), "s3cr3t");
  assert.match(text(view.root.find((node) => node.props?.["data-testid"] === "inbound-url")), /\/api\/v1\/webhooks\/w2\/trigger$/);
});

test("A Jira change source asks for its JQL and needs no URL", async () => {
  const { pollQueryLabel } = await import("../../src/admin/components/inboundWebhooks/inboundWebhookModel.ts");
  assert.equal(pollQueryLabel("jira_change"), "Which issues (JQL)");
  assert.equal(pollQueryLabel("servicenow_change"), "Which incidents (encoded query)");
  const { InboundSecretFields } = makeLoader()("admin/components/inboundWebhooks/InboundSecretFields.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(InboundSecretFields, { webhook: { ...HOOK, polled: true } })); });
  assert.match(text(view.root), /needs no URL/);
});

test("review: the create form offers New action…, Send the result to, and the explicit timestamp setting", async () => {
  const calls = [];
  const readJson = async (url, init) => {
    calls.push([init?.method ?? "GET", url, init?.body ? JSON.parse(init.body) : null]);
    if (url === "/admin/chat/api/panel/channels") return [{ id: 7, name: "Ops room", project_id: "p1" }];
    if (init?.method === "POST") return { ...HOOK, id: "w3", secret: "s" };
    return [];
  };
  const { InboundWebhookCreateDrawer } = makeLoader({ "/AutomationIcon": { AutomationIcon: () => null } })(
    "admin/components/inboundWebhooks/InboundWebhookCreateDrawer.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(InboundWebhookCreateDrawer, {
      sources: [{ key: "generic", label: "Any JSON", polled: false, samples: [] }], projects: [{ id: "p1", name: "Ops" }],
      actions: [{ id: "t1", name: "Incident analysis", project_id: "p1" }], readJson, onCreated() {}, onOpen() {}, onClose() {},
    }));
  });
  const fields = () => view.root.findAll((node) => node.type === "input" || node.type === "select");
  await act(async () => { fields()[0].props.onChange({ target: { value: "Generic" } }); });
  await act(async () => { fields()[1].props.onChange({ target: { value: "p1" } }); });
  const start = fields()[2];
  assert.ok(start.findAll((node) => node.type === "option").some((node) => text(node) === "New action…"));
  await act(async () => { start.props.onChange({ target: { value: "t1" } }); });
  const result = fields()[3];
  assert.deepEqual(result.findAll((node) => node.type === "option").map(text),
    ["Where the action already sends it", "Run history only", "Ops room"]);
  await act(async () => { fields()[3].props.onChange({ target: { value: "7" } }); });
  const box = fields()[4];
  assert.equal(box.props.checked, false, "Any JSON senders can sign a timestamp: the setting starts off");
  await act(async () => { view.root.find((node) => node.type === "button" && text(node) === "Create webhook").props.onClick(); });
  const post = calls.find(([method]) => method === "POST")[2];
  assert.equal(post.result_channel_id, 7);
  assert.equal(post.accept_untimestamped, false);
});

// The latest alerts showed the raw status "rejected_replay" and dates over three lines.
test("every outcome reads in words and the time stays on one line", () => {
  assert.equal(outcomeLabel("rejected_replay"), "Duplicate");
  assert.equal(outcomeLabel("rejected_signature"), "Rejected");
  assert.equal(outcomeLabel("skipped_something_new"), "Skipped something new", "never the code");
  assert.equal(outcomeLabel(""), "Call");
  // The alerts are a DataTable; the Received column keeps one line and the outcome is a StatusLabel.
  const rows = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)),
    "../../src/admin/components/inboundWebhooks/InboundEventRows.tsx"), "utf8");
  assert.match(rows, /key: "time",\s+header: "Received",\s+nowrap: true,/);
  assert.match(rows, /<StatusLabel label=\{outcomeLabel\(event\.outcome\)\}/);
});

test("an outcome's colour follows the one state scale: only exceptions are coloured", () => {
  const { outcomeStatusTone } = makeLoader({ "/AutomationIcon": { AutomationIcon: () => null } })(
    "admin/components/inboundWebhooks/InboundEventRows.tsx");
  assert.equal(outcomeStatusTone("completed"), "success");
  assert.equal(outcomeStatusTone("started"), "info");
  assert.equal(outcomeStatusTone("rejected_signature"), "problem");
  assert.equal(outcomeStatusTone("failed"), "problem");
  assert.equal(outcomeStatusTone("needs_setup"), "attention");
  assert.equal(outcomeStatusTone("rejected_replay"), "neutral", "a duplicate is not a failure");
  assert.equal(outcomeStatusTone("grouped"), "neutral");
});


test("pull request and CI webhooks are accepted without a timestamp, and the form says why it stays on", () => {
  for (const source of ["scm_pull_request", "ci_build"]) {
    assert.ok(cannotSignTimestamp(source));
    assert.match(timestampFixedReason(source), /GitHub, GitLab and Bitbucket send no timestamp header/);
  }
  assert.ok(cannotSignTimestamp("grafana") && timestampFixedReason("grafana") === "", "the others stay a choice");
  assert.equal(cannotSignTimestamp("jira_issue"), false);
});
