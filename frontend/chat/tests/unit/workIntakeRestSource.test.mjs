// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workIntakeRestSource.test.mjs
//
// Custom REST as a Work source (backend) and the neutral write-back names: the form a stored intake
// opens with, the role-required rule, dot-path validation, the request body the server stores, the dry run's answer,
// refusals in words at their field, and the Sync mode read under both names. Names and values are invented.
import assert from "node:assert/strict";
import { test } from "node:test";

import { mappingProblems, pathProblem, restBodyParts, roleRule, statusRowProblems, writeBackSync } from "../../src/chat/work/intake/restIntakeModel.ts";
import { refusalOf, stepOfField } from "../../src/chat/work/intake/restIntakeRefusals.ts";
import { restFormOf } from "../../src/chat/work/intake/restIntakeForm.ts";
import { sampleView } from "../../src/chat/work/intake/restIntakeSample.ts";
import { draftPayload, editableDraft, newDraft, stepProblem, withDiscovery } from "../../src/chat/work/intake/workIntakeDraft.ts";
import { neutralLabel, policyWithSyncMode, sourceStatusOf, sourceTransitionOf, syncModeOf } from "../../src/chat/work/syncNames.ts";

const LIST = { op_key: "list_tickets", name: "list_tickets", method: "GET", path: "/tickets", roles: ["agent", "admin"],
  scoped_roles: ["agent"], role_required: true };
const OPEN = { ...LIST, op_key: "list_all", roles: ["admin"], scoped_roles: [], role_required: false };
const FOUND = { source_type: "custom_rest", work_states: [{ key: "intake", label: "Intake" }, { key: "development", label: "Development" }],
  list_operations: [LIST, OPEN], write_operations: [], fields: { required: ["key", "title", "status"], optional: ["id"] } };
const BASE = { automation_mode: "needs_review", automation_labels: [], automation_exclude_labels: [] };

const filled = (overrides = {}) => ({
  ...restFormOf({}, {}),
  operation: "list_tickets", role: "agent", fields: { key: "number", title: "summary", status: "state.name" }, ...overrides,
});

test("a scoped operation needs a role from its grants; an unscoped one reads as any granted role", () => {
  assert.equal(roleRule(LIST, "").required, true);
  assert.match(roleRule(LIST, "").problem, /scope is enforced as that role/);
  assert.equal(roleRule(LIST, "Agent").problem, null, "roles match without regard to case, like the server's grants");
  assert.match(roleRule(LIST, "viewer").problem, /viewer has no grant/);
  assert.deepEqual(roleRule(LIST, "agent").roles, ["agent", "admin"], "the roles offered are the grants' roles");
  assert.equal(roleRule(OPEN, "").problem, null);
  assert.match(roleRule({ ...OPEN, roles: [] }, "").problem, /No role is granted/);
  const draft = { ...newDraft("custom_rest", "desk"), rest: filled({ role: "" }) };
  assert.match(stepProblem(1, draft, FOUND), /Pick the role to read as/, "the What step cannot be left without the role");
  assert.equal(stepProblem(1, { ...draft, rest: filled() }, FOUND), null);
});

test("dot paths follow the server's rule; key, title and status are required", () => {
  for (const ok of ["number", "fields.summary", "sys.id", "a_b.$c.@d:e-f"]) assert.equal(pathProblem(ok), null, ok);
  assert.match(pathProblem("fields summary"), /no spaces/);
  assert.match(pathProblem("fields..summary"), /no empty step/);
  assert.match(pathProblem(".summary"), /no empty step/);
  assert.match(pathProblem("fields[0]"), /letters, digits/);
  assert.deepEqual(Object.keys(mappingProblems({ key: "number", title: "" })), ["title", "status"]);
  assert.deepEqual(Object.keys(mappingProblems({ key: "number", title: "t", status: "s", url: "links[0]" })), ["url"]);
  const draft = { ...newDraft("custom_rest", "desk"), rest: filled({ fields: { key: "number", title: "summary" } }) };
  assert.match(stepProblem(3, draft, FOUND), /^Status: Status is required/);
});

test("status rows: one state per status, matched case-insensitively", () => {
  assert.deepEqual(statusRowProblems([{ status: "Working", state: "development" }, { status: "working ", state: "intake" }]),
    { 1: "This status is mapped twice." });
  assert.deepEqual(statusRowProblems([{ status: "New", state: "" }, { status: "", state: "" }]), { 0: "Pick the Octryx state." },
    "an empty new row is no problem yet");
});

test("the body the server stores: what, how with mapping, status mapping, write-back and auto-analysis", () => {
  const form = filled({
    arguments: [{ name: "state", value: "open" }, { name: " ", value: "ignored" }],
    fields: { key: " number ", title: "summary", status: "state.name", url: "" },
    statusRows: [{ status: "Working", state: "development" }, { status: "", state: "" }],
    closedStatuses: ["Resolved", " "],
    writeOperation: "update_ticket", writeArguments: [{ name: "id", value: "{source_key}" }], writeBody: '{"status": "{target_status}"}',
    autoAnalyze: true,
  });
  assert.deepEqual(restBodyParts(form, BASE), {
    what: { operation: "list_tickets", role: "agent", arguments: { state: "open" } },
    how: { ...BASE, field_mapping: { key: "number", title: "summary", status: "state.name" }, status_mapping: { Working: "development" },
      closed_statuses: ["Resolved"], auto_analyze_new: true,
      write_back: { operation: "update_ticket", arguments: { id: "{source_key}" }, body: { status: "{target_status}" } } },
  });
  const readOnly = restBodyParts(filled({ role: " " }), BASE);
  assert.equal(readOnly.how.write_back, null, "no write operation means read only");
  assert.equal(readOnly.what.role, null);

  const payload = draftPayload({ ...newDraft("custom_rest", "desk"), id: "i-1", is_active: false, rest: form });
  assert.deepEqual(Object.keys(payload).sort(), ["connection_id", "how", "name", "schedule", "source_type", "what"],
    "no form state or read-only keys are sent");
  assert.equal(payload.name, "REST desk · list_tickets");
  assert.deepEqual(payload.schedule, { preset: "manual", cron: null }, "a new REST source syncs only when asked");
});

test("a stored intake opens with its form; discovery never touches a REST draft", () => {
  const stored = { ...newDraft("custom_rest", "desk"), id: "i-1", rest: undefined,
    what: { operation: "list_tickets", role: "agent", arguments: { state: "open" }, max_items: 5000 },
    how: { ...BASE, field_mapping: { key: "number" }, status_mapping: { working: "development" }, closed_statuses: ["Resolved"],
      auto_analyze_new: true, write_back: { operation: "update_ticket", arguments: { id: "{source_key}" }, body: { status: "{target_status}" } } } };
  const form = editableDraft(stored).rest;
  assert.deepEqual(form.arguments, [{ name: "state", value: "open" }]);
  assert.deepEqual(form.statusRows, [{ status: "working", state: "development" }]);
  assert.equal(form.writeOperation, "update_ticket");
  assert.deepEqual(JSON.parse(form.writeBody), { status: "{target_status}" });
  assert.equal(form.autoAnalyze, true);
  assert.deepEqual(restBodyParts(form, BASE).how.write_back, stored.how.write_back, "opening and saving keeps the write-back");
  assert.equal(withDiscovery(stored, FOUND), stored, "REST discovery has no Jira field roles to merge");
});

test("the dry run: mapped rows with their fields, the dropped count and why", () => {
  const view = sampleView({ records: 5, skipped_invalid: 1, closed: 1, dropped_out_of_scope: 2, last_page: true, role: "agent",
    items: [{ source_key: "D-1", title: "Printer offline", source_status: "Working", work_state: "development", issue_type: "incident",
      reporter: "ana@example.test", assignee: null, parent_key: null, labels_json: ["hw"] }] }, FOUND.work_states);
  assert.deepEqual(view.rows, [{ key: "D-1", title: "Printer offline", status: "Working", becomes: "Development",
    extra: "type incident · reporter ana@example.test · labels hw" }]);
  assert.deepEqual([view.read, view.mapped, view.dropped, view.role, view.closed], [5, 4, 3, "agent", 1]);
  assert.deepEqual(view.droppedReasons, ["1 without a key, title or status", "2 outside the role's data scope"]);
  assert.equal(sampleView({ items: [] }, []).dropped, 0);
});

const refusal = (status, detail) => Object.assign(new Error(detail.message ?? "x"), { status, code: detail.code ?? null, detail });

test("refusals read as words at their field, on the step that edits it", () => {
  const role = refusalOf(refusal(422, { code: "custom_rest_role_required", field: "what.role", message: "what.role The list operation…" }));
  assert.equal(role.field, "what.role");
  assert.match(role.text, /enforced as that role/);
  assert.equal(stepOfField(role.field), 1);
  assert.equal(refusalOf(refusal(409, { code: "custom_rest_role_not_granted" })).field, "what.role", "the sample's 409 has no field; the code names it");
  const path = refusalOf(refusal(422, { code: "invalid_request", field: "how.field_mapping.title", message: "how.field_mapping.title must be a dotted record path" }));
  assert.deepEqual([path.field, path.text], ["how.field_mapping.title", "Title: use a dot path, like fields.summary."]);
  assert.equal(stepOfField(path.field), 3);
  assert.deepEqual(refusalOf(refusal(422, { code: "invalid_request", field: "what.max_items", message: "what.max_items must be an integer from 1 to 100000" })),
    { field: "what.max_items", text: "Must be an integer from 1 to 100000" }, "no technical field name in the words");
  assert.equal(refusalOf(refusal(422, { code: "custom_rest_write_back_operation_invalid", field: "how.write_back.operation" })).field, "how.write_back.operation");
  assert.match(refusalOf(refusal(409, { code: "custom_rest_unauthorized" })).text, /refused the call \(unauthorized\)/);
  assert.match(refusalOf(refusal(403, {})).text, /Workspace admin or owner/);
  assert.match(refusalOf(refusal(502, { code: "custom_rest_request_failed" })).text, /did not answer as expected/);
  for (const status of [400, 404, 409, 422]) assert.ok(refusalOf(refusal(status, {})).text, `every ${status} has words`);
});

test("neutral write-back names: one label for every source; a source-specific name reads nothing", () => {
  assert.deepEqual(["source_status", "source_transition", "sync_mode"].map(neutralLabel),
    ["Status in the source", "Transition used to write back", "Sync"]);
  assert.equal(neutralLabel("jira_status"), "");
  assert.equal(neutralLabel("comment_template"), "");
  assert.equal(sourceStatusOf({ source_status: "Done" }), "Done");
  assert.equal(sourceStatusOf({ jira_status: "Erledigt" }), "");
  assert.equal(sourceTransitionOf({ source_transition: " Resolve " }), "Resolve");
});

test("Sync: sync_mode alone decides and a change is sent under it", () => {
  assert.equal(syncModeOf({ sync_mode: "execute" }), "execute");
  assert.equal(syncModeOf({ jira_sync_mode: "execute" }), "");
  assert.equal(syncModeOf({}), "");
  assert.deepEqual(policyWithSyncMode({ sync_mode: "dry_run_only", conflict_policy: "x" }, "execute"),
    { sync_mode: "execute", conflict_policy: "x" });
  const workflow = (project_id, mode, is_active = true) => ({ project_id, is_active, sync_policy: { sync_mode: mode } });
  assert.equal(writeBackSync([], "ws").mode, "none");
  assert.equal(writeBackSync([workflow("ws", "dry_run_only"), workflow("other", "execute")], "ws").mode, "dry_run",
    "another Workspace's workflow does not count");
  assert.equal(writeBackSync([workflow(null, "execute")], "ws").mode, "execute");
  assert.equal(writeBackSync([workflow("ws", "execute", false)], "ws").mode, "none", "an inactive workflow writes nothing");
});

test("the overview names a REST intake's operation and role as the scalars the server sends; a missing list is null", async () => {
  const { whatLabel, sourceLabel } = await import("../../src/chat/work/intake/workIntakeModel.ts");
  assert.equal(whatLabel({ source_type: "custom_rest", what: { operation: "list_tickets", role: "operator" } }), "Operation list_tickets · as operator");
  assert.equal(whatLabel({ source_type: "custom_rest", what: { operation: "list_tickets", role: null, custom_query: false } }), "Operation list_tickets");
  assert.equal(whatLabel({ source_type: "custom_rest", what: { operation: null, role: null } }), "No operation");
  assert.equal(whatLabel({ source_type: "jira", what: { project_keys: ["OPS"], issue_types: null, labels_include: null, labels_exclude: null } }),
    "Project OPS");
  assert.equal(whatLabel({ source_type: "servicenow", what: { tables: null, excluded_states: null } }), "incident");
  assert.equal(sourceLabel("custom_rest"), "Custom REST");
});
