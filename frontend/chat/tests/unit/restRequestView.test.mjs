// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/restRequestView.test.mjs
// Backend: a custom REST write waits for a person with the exact request as its preview. The person must see what
// is sent where, within which scope, and never a credential: the write plan's raw fields (as the model wrote them) are
// replaced by the server's masked body.
import assert from "node:assert/strict";
import { test } from "node:test";

import { restRequestLines, restRequestView } from "../../src/chat/approval/restRequestView.ts";
import { writePlanView } from "../../src/chat/approval/writePlanView.ts";

const DETAILS = [
  "api: Demo Tickets",
  "operation: create_ticket",
  "request: POST http://127.0.0.1:8874/tickets",
  "connection: Local tickets",
  "headers: X-Request-Source",
  'body: {"title": "Printer on floor 3", "api_token": "[redacted]", "assignment_group": "G1"}',
  "scope set by Octryx: body assignment_group=G1",
];

// rest_connector/preview.py's payload, as the central approval stores it.
const PREVIEW = {
  kind: "rest_request",
  title: "POST Demo Tickets: create_ticket",
  summary: "POST http://127.0.0.1:8874/tickets",
  method: "POST",
  api: "Demo Tickets",
  operation: "create_ticket",
  connection: "Local tickets",
  url: "http://127.0.0.1:8874/tickets",
  header_names: ["X-Request-Source"],
  body: { title: "Printer on floor 3", api_token: "[redacted]", assignment_group: "G1", meta: { source: "chat" } },
  details: DETAILS,
  fields_shown: true,
  toolName: "rest__demo_tickets__create_ticket",
};

test("the approval preview reads as the request: method, path, API › operation, connection, body, scope", () => {
  const view = restRequestView(PREVIEW);
  assert.equal(view.title, "POST /tickets on Demo Tickets › create_ticket");
  assert.deepEqual([view.connection, view.host, view.path], ["Local tickets", "127.0.0.1:8874", "/tickets"]);
  assert.deepEqual(view.fields.map((field) => [field.label, field.value]), [
    ["Title", "Printer on floor 3"], ["Api token", "[redacted]"], ["Assignment group", "G1"], ["Meta", '{"source":"chat"}'],
  ]);
  assert.match(view.bodyJson, /"source": "chat"/, "a nested body is also offered as JSON");
  assert.deepEqual(view.scope, ["body assignment_group = G1"]);
  assert.deepEqual(restRequestLines(view), [
    "Sent to http://127.0.0.1:8874/tickets",
    "Scope set by Octryx: body assignment_group = G1",
    "Header names: X-Request-Source",
  ]);
  assert.equal(restRequestView({ kind: "command", details: [] }), null, "other previews keep their own card");
});

test("a call the server will refuse says so before anyone approves it", () => {
  const view = restRequestView({
    ...PREVIEW, connection: null, url: "/tickets",
    details: ["connection: none active for this Workspace (the call will be refused)",
      "scope: outside your access to this operation (the call will be refused)"],
  });
  assert.deepEqual([view.noConnection, view.outsideAccess, view.connection, view.path], [true, true, "", "/tickets"]);
  assert.match(restRequestLines(view).join("\n"), /No active connection.*\n.*Outside your access/);
});

test("in a write plan a REST write shows the server's masked body, never the model's raw fields", () => {
  const plan = writePlanView({
    kind: "write_plan", plan_id: "wp_1", request: "Open a desk ticket", scope: [],
    writes: [{
      index: 0, tool: "rest__demo_tickets__create_ticket", connector: "dynamic_rest", connection: "Local tickets",
      why: "The printer is broken",
      fields: { body: { title: "Printer on floor 3", api_token: "sk-li" + "ve0123456789abcdef" } },
      title: "POST Demo Tickets: create_ticket", summary: "POST http://127.0.0.1:8874/tickets", details: DETAILS,
    }],
  });
  const [write] = plan.writes;
  assert.equal(write.action, "POST /tickets");
  assert.equal(write.subject, "Demo Tickets › create_ticket");
  assert.equal(write.connection, "Local tickets");
  assert.deepEqual(write.fields.map((field) => field.value), ["Printer on floor 3", "[redacted]", "G1"]);
  assert.ok(!JSON.stringify(plan).includes("sk-li" + "ve0123456789abcdef"), "the raw token never reaches the card");
  assert.ok(write.details.includes("Scope set by Octryx: body assignment_group = G1"));
});

test("the central approval's recorded payload (kind tool_execution, toolName rest__…) reads the same", () => {
  // Recorded from the local server: the gate wraps the REST preview; api and operation are details lines.
  const recorded = {
    kind: "tool_execution", title: "POST Demo Tickets Desk: create_ticket", summary: "POST http://127.0.0.1:8878/tickets",
    details: ["rule: require_for_risks", "risk: write", "api: Demo Tickets Desk", "operation: create_ticket",
      "request: POST http://127.0.0.1:8878/tickets", "connection: Desk (local)", "headers: X-Request-Source",
      'body: {"title": "Nightly stock sync failed", "priority": 1, "assignment_group": "G1"}',
      "scope set by Octryx: body assignment_group=G1"],
    toolName: "rest__desk__create_ticket", connection: "Desk (local)", url: "http://127.0.0.1:8878/tickets", method: "POST",
    header_names: ["X-Request-Source"], body: { title: "Nightly stock sync failed", priority: 1, assignment_group: "G1" },
  };
  const view = restRequestView(recorded);
  assert.equal(view.title, "POST /tickets on Demo Tickets Desk › create_ticket");
  assert.deepEqual(view.fields.map((field) => field.value), ["Nightly stock sync failed", "1", "G1"]);
  assert.equal(view.bodyJson, "", "a flat body needs no JSON view");
  assert.equal(restRequestView({ kind: "tool_execution", toolName: "create_jira_ticket", details: [] }), null);
});
