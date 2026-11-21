// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/securityControls.test.mjs
//
// The security controls of in the UI: an emergency stop holds new starts until an admin resumes,
// automatic analyses only propose reporter questions and a person sends them, a remote MCP tool's risk class
// And the platform's `unattended_allowed_tools`. Requests are stubs.
import assert from "node:assert/strict";
import { test } from "node:test";

import { act, byTestId, click, render, server, text, tick } from "./settingsRenderHarness.mjs";
import {
  askReporterRefusalText,
  canSendQuestions,
  holdByText,
  mcpToolBindings,
  newStartsHeld,
  readAskReporterAnswer,
  readHold,
  readReporterQuestion,
  reporterQuestionText,
  resumeBody,
  resumeOffer,
  resumeRefusalText,
  resumeResultText,
  riskPatch,
  unattendedToolProblem,
} from "../../src/admin/components/securityControls/securityControlsModel.ts";
import { readPolicy, workspaceApprovalBody } from "../../src/admin/components/toolApprovals/toolApprovalsModel.ts";

const refusal = (status, code, message = "") => Object.assign(new Error(message), { status, code });

test("resume: the scope's body, a platform stop that still holds, and refusals in words", () => {
  assert.equal(newStartsHeld({ new_starts_held: true, runs: [] }), true);
  assert.equal(newStartsHeld({ runs: [] }), false, "an answer without the field holds nothing");
  assert.deepEqual(resumeBody("ws-1", " storm over "), { workspace_id: "ws-1", reason: "storm over" });
  assert.deepEqual(resumeBody("", "done"), { reason: "done" }, "no workspace_id resumes the platform");
  assert.match(resumeRefusalText(refusal(422, "reason_required")), /Say why new starts may run again/);
  assert.match(resumeResultText({ new_starts_held: false }, "Kitchen helper"), /^New starts run again in Kitchen helper\./);
  assert.match(resumeResultText({ new_starts_held: true }, "Kitchen helper"), /platform stop still holds/);
  assert.match(resumeRefusalText(refusal(409, "not_stopped")), /Nothing to resume here/);
  assert.match(resumeRefusalText(refusal(403, "platform_admin_required")), /Only platform admins/);
  assert.equal(resumeRefusalText(refusal(500, "", "boom")), "Not resumed: boom");
});

test("who holds: a platform hold in a Workspace view offers the platform view to platform admins, nothing to others", () => {
  const preview = (held_by, by = { id: "u", name: "Anna" }) => ({
    new_starts_held: true, held_by, hold: { scope: held_by, workspace_id: null, by, at: "2026-11-15T13:02:00Z", reason: "incident" },
  });
  const platform = readHold(preview("platform"));
  assert.deepEqual(platform, { scope: "platform", by: "Anna", at: "2026-11-15T13:02:00Z", reason: "incident" });
  assert.equal(holdByText(platform, "Kitchen helper"), "Stopped for the whole platform by Anna");
  assert.equal(holdByText(readHold(preview("workspace", null)), "Kitchen helper"), "Stopped for Kitchen helper", "an unknown person is left out");
  assert.equal(readHold({ new_starts_held: true }), null, "an answer without held_by names nobody");
  assert.equal(resumeOffer(platform, "ws-1", true), "platform");
  assert.equal(resumeOffer(platform, "ws-1", false), "none", "never a Workspace resume that answers 409");
  assert.equal(resumeOffer(platform, "", true), "resume", "the platform view resumes the platform");
  assert.equal(resumeOffer(readHold(preview("workspace")), "ws-1", false), "resume");
  assert.equal(resumeOffer(null, "ws-1", false), "resume");
});

test("ask reporter answer: not sent keeps the questions proposed and says why; sent shows the sent state", () => {
  const proposed = { state: "proposed", questions: 1 };
  const off = readAskReporterAnswer({ sent: false, attempt: { state: "skipped", reason: "ask_reporter_off" }, reporter_question: proposed });
  assert.equal(off.sent, false);
  assert.equal(canSendQuestions(off.question, 1), true, "the button stays");
  assert.equal(off.attempt, "Not sent: asking the reporter is switched off for this Workspace.");
  assert.equal(readAskReporterAnswer({ sent: false, attempt: { state: "failed", reason: "jira_http_502" }, reporter_question: proposed }).attempt,
    "Not sent: Jira did not answer (HTTP 502).");
  assert.equal(readAskReporterAnswer({ sent: false, attempt: { state: "failed", reason: "odd_code_x" }, reporter_question: proposed }).attempt,
    "Not sent: the questions could not be posted to Jira.", "an unknown code shows no raw id");
  const sent = readAskReporterAnswer({ sent: true, attempt: { state: "posted" }, reporter_question: { state: "posted", questions: 1 } });
  assert.deepEqual([sent.sent, sent.attempt, sent.question.state], [true, null, "posted"]);
});

test("reporter questions: only proposed ones can be sent; every outcome reads as words", () => {
  const proposed = readReporterQuestion({ state: "proposed", reason: "awaits_person", questions: 2 });
  assert.deepEqual(proposed, { state: "proposed", questions: 2 });
  assert.equal(canSendQuestions(proposed, 2), true);
  assert.equal(canSendQuestions(readReporterQuestion({ state: "posted", questions: 2 }), 2), false);
  assert.equal(canSendQuestions(null, 2), false, "a manual analysis without a record offers no send");
  assert.equal(canSendQuestions(proposed, 0), false);
  assert.match(reporterQuestionText(proposed), /nothing was posted\. 2 questions wait/);
  assert.equal(reporterQuestionText(readReporterQuestion({ state: "skipped", reason: "ask_reporter_off" })),
    "Not sent: asking the reporter is switched off for this Workspace.");
  assert.equal(reporterQuestionText(readReporterQuestion({ state: "failed", reason: "jira_http_403" })), "Not sent: Jira answered with error 403.");
  assert.equal(readReporterQuestion({ state: "weird" }), null);
  assert.match(askReporterRefusalText(refusal(403, null, "Work management requires admin or operation role")), /may not send/);
  assert.match(askReporterRefusalText(refusal(404, "analysis_not_found")), /no longer exists/);
});

test("MCP tool risk: one row per mirrored tool of this server; the update keeps every stored policy key", () => {
  const bindings = [
    { id: "m", capability_kind: "mcp_capability", source_entity_type: "mcp_server_mirror", binding_config: { serverName: "tickets" }, policy_config: {} },
    { id: "b", capability_kind: "mcp_capability", source_entity_type: "mcp_server_tool", is_enabled: true,
      binding_config: { serverName: "tickets", toolName: "add_comment" }, policy_config: { risk: "unknown", source: "mcp_capability_mirror" } },
    { id: "a", capability_kind: "mcp_capability", source_entity_type: "mcp_server_tool",
      binding_config: { serverName: "tickets", toolName: "get_ticket" }, policy_config: { risk: "READ" } },
    { id: "o", capability_kind: "mcp_capability", source_entity_type: "mcp_server_tool",
      binding_config: { serverName: "other", toolName: "x" }, policy_config: {} },
    { id: "g", capability_kind: "agent", binding_config: {}, policy_config: {} },
  ];
  const rows = mcpToolBindings(bindings, "Tickets");
  assert.deepEqual(rows.map((row) => [row.id, row.tool, row.risk, row.enabled]), [["b", "add_comment", "unknown", true], ["a", "get_ticket", "read", false]]);
  assert.deepEqual(riskPatch(rows[0], "write"), { policy_config: { risk: "write", source: "mcp_capability_mirror" } });
});

test("unattended tools: the platform default carries the list, a Workspace body never does", () => {
  assert.deepEqual(readPolicy({ unattended_allowed_tools: ["add_jira_comment"] }).unattended_allowed_tools, ["add_jira_comment"]);
  const policy = { require_for_risks: ["write"], require_for_tools: [], exempt_tools: [], unattended_allowed_tools: ["x"] };
  assert.deepEqual(workspaceApprovalBody("add", policy), { mode: "add", require_for_risks: ["write"], require_for_tools: [], exempt_tools: [] });
  assert.deepEqual(workspaceApprovalBody("inherit", policy), { mode: "inherit" });
  assert.equal(unattendedToolProblem("tickets:add_comment", []), null, "an MCP capability key is a valid name");
  assert.match(unattendedToolProblem("add comment", []), /letters, digits/);
  assert.match(unattendedToolProblem("x", ["x"]), /already listed/);
});

test("rendered platform default: adding an unattended tool shows the warning and saves the whole default", async () => {
  const saved = [];
  const props = (workspace) => ({
    title: "Platform default", workspace, mode: "add",
    policy: { require_for_risks: ["admin"], require_for_tools: [], exempt_tools: ["send_email"], unattended_allowed_tools: [] },
    defaults: { require_for_risks: [], require_for_tools: [], exempt_tools: [] }, risks: ["admin"],
    tools: [{ name: "add_jira_comment", risk: "write" }], busy: false, problem: null, onClose: () => {},
    onSave: (mode, policy) => saved.push(JSON.parse(JSON.stringify(policy))),
  });
  const view = await render("admin/components/toolApprovals/ApprovalPolicyDrawer.tsx", "ApprovalPolicyDrawer", server(() => ({ status: 200, body: {} })), props(false));
  try {
    assert.match(text(byTestId(view, "approval-unattended")[0]), /may write in runs no person started, without a per-call approval/);
    await act(async () => { byTestId(view, "approval-unattended-input")[0].props.onChange({ target: { value: "add_jira_comment" } }); });
    await click(view, "approval-unattended-add");
    await click(view, "approval-save");
    assert.deepEqual(saved[0], { require_for_risks: ["admin"], require_for_tools: [], exempt_tools: ["send_email"], unattended_allowed_tools: ["add_jira_comment"] });
  } finally { act(() => view.unmount()); }
  const workspace = await render("admin/components/toolApprovals/ApprovalPolicyDrawer.tsx", "ApprovalPolicyDrawer", server(() => ({ status: 200, body: {} })), props(true));
  try {
    assert.equal(byTestId(workspace, "approval-unattended").length, 0, "a Workspace has no unattended list");
  } finally { act(() => workspace.unmount()); }
});

test("rendered reporter questions: a person confirms, the route is posted once, the sent state and a refusal read as words", async () => {
  const answers = [
    { status: 200, body: { sent: false, attempt: { state: "failed", reason: "jira_http_500" }, reporter_question: { state: "proposed", questions: 2 } } },
    { status: 200, body: { sent: true, attempt: { state: "posted" }, reporter_question: { state: "posted", questions: 2, at: "2026-11-15T08:00:00Z" } } },
    { status: 403, body: { detail: "Work management requires admin or operation role" } },
  ];
  const srv = server(() => answers.shift());
  const props = { workItemId: "wi 1", analysisId: "an-1", questions: ["Q1?", "Q2?"], initial: { state: "proposed", questions: 2 } };
  const view = await render("chat/work/incident/ReporterQuestions.tsx", "ReporterQuestions", srv, props);
  try {
    assert.match(text(byTestId(view, "analysis-questions-state")[0]), /nothing was posted/);
    await click(view, "analysis-questions-send");
    assert.equal(srv.calls.length, 0, "nothing is posted before the confirmation");
    const confirm = byTestId(view, "analysis-questions-confirm")[0];
    await act(async () => { confirm.findAll((node) => node.type === "button")[0].props.onClick(); });
    await tick();
    assert.deepEqual(srv.calls.map((call) => [call.method, call.url]),
      [["POST", "/api/v1/secure-work/work-items/wi%201/analyses/an-1/ask-reporter"]]);
    assert.match(text(byTestId(view, "analysis-questions-error")[0]), /Jira did not answer \(HTTP 500\)/);
    assert.match(text(byTestId(view, "analysis-questions-state")[0]), /nothing was posted/, "not sent stays proposed");
    await click(view, "analysis-questions-send");
    await act(async () => { byTestId(view, "analysis-questions-confirm")[0].findAll((node) => node.type === "button")[0].props.onClick(); });
    await tick();
    assert.equal(srv.calls.length, 2, "the button stayed and sends again");
    assert.equal(byTestId(view, "analysis-questions-error").length, 0);
    assert.match(text(byTestId(view, "analysis-questions-state")[0]), /Sent to the reporter in Jira \(2 questions\)/);
    assert.equal(byTestId(view, "analysis-questions-send").length, 0, "sent questions offer no second send");
  } finally { act(() => view.unmount()); }
  const denied = await render("chat/work/incident/ReporterQuestions.tsx", "ReporterQuestions", srv, props);
  try {
    await click(denied, "analysis-questions-send");
    const confirm = byTestId(denied, "analysis-questions-confirm")[0];
    await act(async () => { confirm.findAll((node) => node.type === "button")[0].props.onClick(); });
    await tick();
    assert.match(text(byTestId(denied, "analysis-questions-error")[0]), /you may not send questions/);
  } finally { act(() => denied.unmount()); }
});
