// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/restApisModel.test.mjs
// Admin › Connections › REST APIs (backend writes): the authorization must be obvious and the bodies must match the
// backend's contract, because the API is called with one technical account and these settings are all that limits it.
import assert from "node:assert/strict";
import { test } from "node:test";

import { OFFERED_TO_NOBODY, TEST_WRITE_NOTE, capabilityLabel, definitionRow, operationKind, operationState, serverWarnings } from "../../src/admin/components/restApis/restOperationsModel.ts";
import { bodyFieldPaths, grantProblems, grantWarning, operationBody, operationDraft, operationWarnings } from "../../src/admin/components/restApis/restOperationEditorModel.ts";
import { callAdmission, filterCalls, refusedScopeText, callsFilterFromSearch, callsQuery } from "../../src/admin/components/restApis/restCallsModel.ts";
import { connectionAuthFields, definitionAuthFields } from "../../src/admin/components/restApis/restAuthModel.ts";
import { connectionBody, connectionDraft, secretState } from "../../src/admin/components/restApis/restConnectionsModel.ts";
import { definitionEditBody, definitionEditDraft, importBody, manualBody, manualOperationBody, schemeChanged, csrfBody } from "../../src/admin/components/restApis/restDefinitionDraftsModel.ts";
import { restErrorView } from "../../src/admin/components/restApis/restErrorsModel.ts";
import { scopeText, testBody, testParameters, testView } from "../../src/admin/components/restApis/restTestCallModel.ts";
import { applyTemplate, apiTemplateText, csrfApplies, csrfDefault, serverRowOfIndex, templateOf, wireNameOf, withScheme, answerBody, choosePreset, editAnswer, isCollectionRead, presetInEffect, presetOptions } from "../../src/admin/components/restApis/restOdataModel.ts";

const op = (patch = {}) => ({
  id: "op1", op_key: "list_tickets", tool_name: "rest__demo__list_tickets", method: "GET", path: "/tickets", summary: "",
  parameters: [
    { name: "group", in: "query", required: false, description: "", schema: { type: "string" } },
    { name: "limit", in: "query", required: false, description: "", schema: { type: "integer" } },
  ],
  request_body: null, enabled: false, read_only: true, is_read: true, llm_name: "", llm_description: "", params_overlay: {},
  grants: [], response_select: [], records_path: "", pagination: { type: "none" }, preset: "", preset_source: "operation",
  ...patch,
});
const err = (status, message) => Object.assign(new Error(message), { status });

test("operation state: reads and writes alike, enabled without grants is offered to nobody", () => {
  const nobody = operationState({ enabled: true, grants: [] });
  assert.deepEqual([nobody.label, nobody.tone], ["Offered to nobody", "attention"]);
  assert.equal(operationState({ enabled: true, grants: [{}] }).label, "On");
  assert.equal(operationState({ enabled: false, grants: [] }).label, "Off");
});

test("a write is marked with the run class the server says it needs (Deliver unless the admin set Change)", () => {
  assert.deepEqual(operationKind({ is_read: true, capability: null }), { label: "Read", write: false, hint: "" });
  const deliver = operationKind({ is_read: false, capability: "deliver" });
  assert.deepEqual([deliver.label, deliver.write], ["Write · Deliver", true]);
  assert.match(deliver.hint, /approval/);
  assert.equal(operationKind({ is_read: false, capability: "change" }).label, "Write · Change");
  assert.equal(operationKind({ is_read: false }).label, "Write · Deliver", "without capability: the default");
  assert.equal(capabilityLabel("change"), "Change");
});

test("editor warnings: scope without result filter, no grants, writes", () => {
  const base = op({ enabled: true });
  const draft = operationDraft(base);
  assert.deepEqual(operationWarnings(base, draft), [OFFERED_TO_NOBODY]);

  const scoped = { role: "agent", workspaceId: "", scope: [{ param: "group", value: "G1" }], bodyScope: [], filterField: "", filterValue: "" };
  assert.match(grantWarning(scoped), /only enforced if the API honours/);
  assert.equal(grantWarning({ ...scoped, filterField: "group", filterValue: "G1" }), null, "a result filter makes the scope hold");
  assert.equal(grantWarning({ ...scoped, scope: [] }), null, "no scope, nothing to warn");
  const withGrant = { ...draft, grants: [scoped] };
  assert.equal(operationWarnings(base, withGrant).length, 1);
  assert.equal(operationWarnings(base, withGrant, false).length, 0, "the Access tab shows it on the grant instead");

  const write = op({ method: "POST", read_only: false, is_read: false });
  assert.deepEqual(operationWarnings(write, { ...operationDraft(write), readOnly: false }), [], "a write is offered like a read");
  assert.deepEqual(operationWarnings(write, { ...operationDraft(write), readOnly: true, enabled: true }), [OFFERED_TO_NOBODY],
    "a POST marked read-only is a read");
});

test("a write's scope warning asks for a body scope, not a result filter", () => {
  const scoped = { role: "agent", workspaceId: "", scope: [{ param: "group", value: "G1" }], bodyScope: [], filterField: "", filterValue: "" };
  assert.match(grantWarning(scoped, true, true), /model still writes the request body.*body scope/);
  assert.equal(grantWarning({ ...scoped, bodyScope: [{ param: "assignment_group", value: "G1" }] }, true, true), null);
  assert.equal(grantWarning(scoped, true, false), null, "no body to write: the parameter scope holds");
  assert.equal(grantWarning({ ...scoped, scope: [], bodyScope: [{ param: "a", value: "1" }] }, true, true), null);
});

test("operation PUT: typed scope values, read_only only for POST, empty overlay left out", () => {
  const base = op();
  const draft = {
    ...operationDraft(base), enabled: true, llmName: " tickets ",
    overlay: { group: { description: "", hidden: false, value: "" }, limit: { description: "", hidden: true, value: "25" } },
    grants: [{ role: "agent", workspaceId: "w1", scope: [{ param: "limit", value: "10" }, { param: "group", value: "G1" }], bodyScope: [], filterField: "group", filterValue: "G1" }],
    responseSelect: "id\n title ,status", recordsPath: "result", presetChoice: "",
    pagination: { ...operationDraft(base).pagination, type: "offset", page_size: "20" },
  };
  const body = operationBody(base, draft);
  assert.equal("read_only" in body, false);
  assert.equal("capability" in body, false, "a read sends no run class");
  assert.equal("idempotent" in body, false, "a GET sends no retry flag");
  assert.equal(body.llm_name, "tickets");
  assert.deepEqual(body.params_overlay, { limit: { hidden: true, value: 25 } });
  assert.deepEqual(body.grants, [{ role: "agent", workspace_id: "w1", scope: { limit: 10, group: "G1" }, result_filter: { field: "group", value: "G1" } }]);
  assert.deepEqual(body.response_select, ["id", "title", "status"]);
  assert.deepEqual(body.pagination, { type: "offset", page_size: 20 });
  assert.equal(operationBody(op({ method: "POST" }), { ...operationDraft(op({ method: "POST" })), readOnly: true }).read_only, true);
});

test("grant problems are said at the field before the server refuses", () => {
  const ok = { role: "service_desk", workspaceId: "", scope: [{ param: "group", value: "G1" }], bodyScope: [], filterField: "a.b", filterValue: "x" };
  assert.deepEqual(grantProblems(ok), {});
  assert.ok(grantProblems({ ...ok, role: "" }).role);
  assert.ok(grantProblems({ ...ok, scope: [{ param: "group", value: " " }] }).scope);
  assert.ok(grantProblems({ ...ok, filterValue: "" }).filter);
  assert.ok(grantProblems({ ...ok, filterField: "", filterValue: "x" }).filter);
  assert.ok(grantProblems({ ...ok, filterField: "a b" }).filter);
  assert.ok(grantProblems({ ...ok, bodyScope: [{ param: "group id", value: "x" }] }).bodyScope, "a body field is a dotted path");
  assert.ok(grantProblems({ ...ok, bodyScope: [{ param: "group", value: "" }] }).bodyScope);
  assert.ok(grantProblems({ ...ok, bodyScope: [{ param: "a", value: "1" }, { param: "a", value: "2" }] }).bodyScope);
  assert.equal(grantProblems({ ...ok, bodyScope: [{ param: "group.id", value: "7" }] }).bodyScope, undefined);
});

test("auth-scheme fields: only what the scheme needs", () => {
  assert.deepEqual(definitionAuthFields("api_key_header"), ["header_name"]);
  assert.deepEqual(definitionAuthFields("bearer"), []);
  assert.deepEqual(connectionAuthFields("none"), []);
  assert.deepEqual(connectionAuthFields("basic").map((field) => [field.name, field.secret]), [["username", false], ["password", true]]);
  assert.deepEqual(connectionAuthFields("oauth2_client_credentials").filter((field) => field.secret).map((field) => field.name), ["client_secret"]);
  const manual = manualBody({ key: "demo", name: "", servers: "https://a.example\nhttps://b.example", scheme: "bearer",
    headerName: "X-Key", queryName: "", tokenUrl: "", scopes: "", timeout: "" });
  assert.deepEqual(manual, { key: "demo", name: "demo", servers: ["https://a.example", "https://b.example"], auth: { scheme: "bearer" }, timeout_seconds: 30 },
    "a header name typed for another scheme is not sent");
  assert.deepEqual(manualBody({ ...manual, key: "o", name: "O", servers: "", scheme: "oauth2_client_credentials", headerName: "", queryName: "",
    tokenUrl: "https://t", scopes: "read write", timeout: "10" }).auth, { scheme: "oauth2_client_credentials", token_url: "https://t", scopes: ["read", "write"] });
});

test("connection bodies: secrets write-only, replace and clear", () => {
  const definition = { servers: ["https://api.example"] };
  const fresh = connectionDraft(null, definition);
  assert.equal(fresh.baseUrl, "https://api.example");
  assert.deepEqual(connectionBody({ ...fresh, secrets: { ...fresh.secrets, api_key: "k1", token: "ignored" } }, "api_key_header", null),
    { name: "", base_url: "https://api.example", project_id: null, api_key: "k1" });

  const existing = { id: "c1", project_id: "w1", owner: "workspace", name: "WS", base_url: "https://x", is_active: true,
    fields: { username: "svc" }, secret_status: { api_key: false, token: false, password: true, client_secret: false }, missing_for_auth: [] };
  const draft = connectionDraft(existing, definition);
  assert.equal(secretState(existing, draft, "password"), "set");
  assert.deepEqual(connectionBody(draft, "basic", existing), { name: "WS", base_url: "https://x", username: "svc" }, "untouched secret left out");
  const cleared = { ...draft, fields: { ...draft.fields, username: "" }, clear: { ...draft.clear, password: true } };
  assert.equal(secretState(existing, cleared, "password"), "clear");
  assert.deepEqual(connectionBody(cleared, "basic", existing), { name: "WS", base_url: "https://x", username: "", clear_password: true });
  const replaced = { ...draft, secrets: { ...draft.secrets, password: "p2" }, clear: { ...draft.clear, password: true } };
  assert.equal(connectionBody(replaced, "basic", existing).password, "p2");
  assert.equal("clear_password" in connectionBody(replaced, "basic", existing), false, "a new value wins over clear");
});

test("import, manual operation and test call bodies", () => {
  assert.deepEqual(importBody({ key: "demo", name: "", source: "url", specText: "x", specUrl: " https://s/openapi.json " }),
    { key: "demo", spec_url: "https://s/openapi.json" });
  assert.deepEqual(importBody({ key: "demo", name: "Demo", source: "text", specText: "openapi: 3.0.3", specUrl: "" }),
    { key: "demo", name: "Demo", spec_text: "openapi: 3.0.3" });
  assert.deepEqual(manualOperationBody({ opKey: "get_ticket", method: "GET", path: "/tickets/{id}", summary: "", query: "id, fields" }).parameters,
    [{ name: "id", in: "path", required: true }, { name: "fields", in: "query", required: false }]);

  const base = op({ params_overlay: { group: { value: "G1" } } });
  assert.deepEqual(testParameters(base).map((param) => param.name), ["limit"], "a fixed parameter is set by Octryx");
  assert.deepEqual(testBody(base, { workspaceId: "w1", mode: "form", values: { limit: "5", group: "" }, json: "" }),
    { body: { workspace_id: "w1", arguments: { limit: 5 } } });
  assert.deepEqual(testBody(base, { workspaceId: "", mode: "json", values: {}, json: "[1]" }), { error: "The arguments must be a JSON object." });
  assert.ok("error" in testBody(base, { workspaceId: "", mode: "json", values: {}, json: "{" }));

  const ok = testView({ api: "Demo", operation: "list_tickets", status_code: 200, data: [], record_count: 2, dropped_out_of_scope: 1,
    next_cursor: null, scope: { params: { group: "G1" }, result_filter: { field: "group", value: "G1" } }, retries: 0, run: { id: "r", duration_ms: 42 } });
  assert.deepEqual([ok.kept, ok.dropped, ok.scope, ok.durationMs], [2, 1, "group = G1 · filter group = G1", 42], "the duration is the run's own");
  const refused = testView({ error: "None of your roles…", code: "not_granted", run: { id: "r", status: "refused", http_status: null } });
  assert.deepEqual([refused.ok, refused.title, refused.status], [false, "Not granted to your roles", "Refused"]);
});

test("refusals map to words at the field", () => {
  assert.deepEqual(restErrorView(err(409, "A REST API with the key 'demo' exists")), { field: "key", text: "Another REST API already uses this key." });
  assert.equal(restErrorView(err(400, "key: 1-24 lower-case letters, digits or '_', starting with a letter")).field, "key");
  assert.equal(restErrorView(err(400, "base_url must be an http(s) URL with a host")).field, "base_url");
  assert.equal(restErrorView(err(409, "This definition already has a connection in that scope")).field, "workspace");
  assert.equal(restErrorView(err(409, "Another operation of this API is already named 'x'")).field, "llm_name");
  assert.deepEqual(restErrorView(err(400, "grant scope names an undeclared parameter: x")),
    { field: "grants", text: "grant scope names an undeclared parameter: x" });
  assert.deepEqual(restErrorView(err(400, "Fetching the OpenAPI document answered HTTP 404"), "import"),
    { field: "spec_url", text: "The address answered HTTP 404; check the URL." });
  assert.equal(restErrorView(err(400, "Not an OpenAPI 3 or Swagger 2 document"), "import").field, "spec");
  assert.equal(restErrorView(err(403, "Forbidden")).text, "Only platform admins manage REST APIs.");
  assert.equal(restErrorView(err(404, "REST API definition not found")).field, null);
  // Backend.
  assert.deepEqual(restErrorView(err(400, "idempotent can be set for PUT and DELETE operations only")),
    { field: "idempotent", text: "Only a PUT or DELETE can be marked safe to repeat." });
  assert.equal(restErrorView(err(400, "capability must be one of deliver, change")).field, "capability");
  assert.deepEqual(restErrorView(err(400, "grant body_scope needs an operation with a request body")),
    { field: "grants", text: "A body scope needs an operation with a request body." });
  assert.equal(restErrorView(err(400, "grant body_scope: not a dotted field path: a b")).text,
    "A body field is a dotted path, e.g. assignment_group or group.id.");
  assert.deepEqual(restErrorView(err(400, "A write operation is not test-called: it would change data in the API. Call it from a chat (write plan) or a workflow (approval).")),
    { field: "test", text: TEST_WRITE_NOTE });
});

test("list rows come from the list endpoint's own counts", () => {
  const row = definitionRow({ id: "d1", key: "demo", name: "Demo", source_kind: "openapi", operations: 3, enabled_operations: 1,
    connections: 2, warnings: 4 });
  assert.deepEqual([row.source, row.enabled, row.total, row.connections, row.warnings], ["OpenAPI import", 1, 3, 2, 4]);
});

test("a server warning naming an operation points to it, by its model name or key", () => {
  const ops = [op({ id: "a", op_key: "list_tickets" }), op({ id: "b", op_key: "get_ticket", llm_name: "ticket" })];
  const found = serverWarnings({ operations: ops, warnings: [
    "Two operations have near-identical descriptions",
    "'list_tickets': enabled without grants: no one can call it until a role is granted.",
    "'ticket': this operation writes; phase 1 refuses it at execution (writes arrive in phase 2).",
  ] });
  assert.deepEqual(found.map((warning) => warning.opId), [null, "a", "b"]);
});

test("a refused scope says what was asked and what each grant allows", () => {
  assert.equal(refusedScopeText({ refused: true, requested: { assignment_group: "G2" },
    allowed: [{ role: "admin", params: { assignment_group: "G1" }, result_filter: { field: "assignment_group", value: "G1" } }] }),
  "Asked for assignment_group = G2; allowed: admin → assignment_group = G1 (filter assignment_group = G1)");
  assert.equal(refusedScopeText({ refused: true, requested: {}, allowed: [] }), "Asked for no scoped value; allowed: no scoped grant");
});

test("editing an API sends only the scheme's fields and keeps the import's source scheme", () => {
  const definition = { name: "Demo", servers: ["https://a", "https://b"], timeout_seconds: 20,
    auth: { scheme: "api_key_header", header_name: "X-Key", source_scheme: "ApiKeyAuth" } };
  const draft = definitionEditDraft(definition);
  assert.deepEqual(definitionEditBody(definition, { ...draft, name: " Demo 2 " }), {
    name: "Demo 2", servers: ["https://a", "https://b"], timeout_seconds: 20,
    auth: { scheme: "api_key_header", header_name: "X-Key", source_scheme: "ApiKeyAuth" } });
  const bearer = { ...draft, scheme: "bearer" };
  assert.ok(schemeChanged(definition, bearer));
  assert.deepEqual(definitionEditBody(definition, bearer).auth, { scheme: "bearer" }, "a new scheme drops the old fields and source");
});

const BODY_OP = (patch = {}) => op({
  op_key: "create_ticket", method: "POST", path: "/tickets", read_only: false, is_read: false, capability: "deliver",
  declared_capability: "", idempotent: false,
  request_body: { required: true, schema: { type: "object", properties: {
    title: { type: "string" }, priority: { type: "integer" }, group: { type: "object", properties: { id: { type: "string" } } },
    tags: { type: "array" },
  } } },
  ...patch,
});

test("write PUT: the run class for a write, idempotent only for PUT/DELETE, typed body scope per grant", () => {
  const post = BODY_OP({ declared_capability: "change", grants: [{ role: "agent", workspace_id: null, scope: {}, result_filter: null,
    body_scope: { "group.id": "G1", priority: 2 } }] });
  const draft = operationDraft(post);
  assert.equal(draft.capability, "change", "the admin's own choice, not the server's effective default");
  assert.deepEqual(draft.grants[0].bodyScope, [{ param: "group.id", value: "G1" }, { param: "priority", value: "2" }]);
  const body = operationBody(post, { ...draft, idempotent: true });
  assert.equal(body.capability, "change");
  assert.equal("idempotent" in body, false, "a POST is never retried: the flag is not sent (the server refuses it)");
  assert.deepEqual(body.grants[0].body_scope, { "group.id": "G1", priority: 2 }, "an integer field stays a number");
  assert.equal(operationBody(BODY_OP(), operationDraft(BODY_OP())).capability, "deliver", "no declaration: Deliver");

  const put = BODY_OP({ method: "PUT", op_key: "update_ticket" });
  assert.equal(operationBody(put, { ...operationDraft(put), idempotent: true }).idempotent, true);
  const none = { ...operationDraft(post), grants: [{ ...draft.grants[0], bodyScope: [] }] };
  assert.equal("body_scope" in operationBody(post, none).grants[0], false, "no body scope: the key is left out");
});

test("body-scope suggestions are the body's scalar fields, nested as dotted paths", () => {
  assert.deepEqual(bodyFieldPaths(BODY_OP()), [
    { path: "title", type: "string" }, { path: "priority", type: "integer" }, { path: "group.id", type: "string" },
  ]);
  assert.deepEqual(bodyFieldPaths(op()), [], "no request body");
});

test("the audit names what admitted a write: an approval opens its detail page, a write plan the chat", () => {
  const approval = callAdmission({ approval_id: "a1b2c3d4-0000", write_plan_id: null, session_id: "s 1" });
  assert.deepEqual(approval, { label: "Approval", id: "a1b2c3d4-0000", shortId: "a1b2c3d4",
    href: "/chat?area=operations&tab=approvalDetail&approval=a1b2c3d4-0000", linkText: "Approval ›" });
  assert.equal(callAdmission({ approval_id: "a1", write_plan_id: null, session_id: null }).href,
    "/chat?area=operations&tab=approvalDetail&approval=a1", "the detail page needs no chat");
  assert.equal(callAdmission({ approval_id: null, write_plan_id: "wp_1", session_id: "s 1" }).href, "/chat?session_id=s%201");
  const plan = callAdmission({ approval_id: null, write_plan_id: "wp_123456789", session_id: null });
  assert.deepEqual([plan.label, plan.href], ["Write plan", null], "no chat: the id is shown quietly");
  assert.equal(callAdmission({ approval_id: null, write_plan_id: null, session_id: "s" }), null, "a read was not admitted");

  const calls = [
    { id: "r", write: false, approval_id: null, write_plan_id: null, failure_category: "" },
    { id: "w", write: true, approval_id: "a", write_plan_id: null, failure_category: "" },
    { id: "gone", write: null, approval_id: null, write_plan_id: null, failure_category: "capability_exceeded" },
  ];
  assert.deepEqual(filterCalls(calls, true).map((call) => call.id), ["w", "gone"]);
  assert.equal(filterCalls(calls, false).length, 3);
  assert.equal(scopeText({ params: {}, body: { assignment_group: "G1" } }), "body assignment_group = G1");
});

// ---- OData (backend) ---------------------------------------------------------------------------------------

test("an OData template sets records path and pages exactly as the backend preset, and an edit makes it 'by hand'", () => {
  const draft = { ...operationDraft(op()), presetChoice: "" };
  const v2 = applyTemplate(draft, "odata_v2");
  assert.deepEqual(operationBody(op(), v2).pagination, { type: "next_url", next_path: "d.__next" });
  assert.equal(operationBody(op(), v2).records_path, "d.results");
  assert.deepEqual(operationBody(op(), applyTemplate(draft, "odata_v2_offset")).pagination,
    { type: "offset", offset_param: "$skip", limit_param: "$top", page_size: 50 });
  assert.equal(editAnswer(draft, { recordsPath: "d.results", pagination: v2.pagination }).presetChoice, "odata_v2",
    "a draft equal to a template is that template's choice, sent as {preset}");
  assert.equal(templateOf(applyTemplate(draft, "odata_v4")), "odata_v4");
  assert.equal(templateOf(operationDraft(op({ records_path: "value", pagination: { type: "next_url", next_path: "@odata.nextLink" } }))), "odata_v4",
    "a stored operation reads back as its template");
  assert.equal(templateOf({ ...v2, recordsPath: "d.items" }), "", "a changed path is no longer the template");
  assert.equal(applyTemplate(v2, ""), v2, "'set by hand' keeps the fields");
});

test("the API's template is the one its imported collection reads carry", () => {
  assert.equal(apiTemplateText([{ preset: "odata_v2" }, { preset: "" }, { preset: "odata_v2" }, {}]), "OData v2 on 2 collection reads");
  assert.equal(apiTemplateText([{ preset: "" }]), "");
});

test("CSRF: on by default only for OData with writes and auth; kept with its header on save; off without auth", () => {
  assert.equal(csrfDefault(true, true, "basic"), true);
  assert.equal(csrfDefault(true, false, "basic"), false);
  assert.equal(csrfDefault(true, true, "none"), false);
  assert.equal(csrfDefault(false, true, "basic"), false);
  const base = { scheme: "none", csrf: false };
  assert.equal(withScheme(base, "basic", true, true).csrf, true, "adding auth to an OData API with writes turns it on");
  assert.equal(withScheme(base, "basic", false, true).csrf, false);
  assert.equal(withScheme({ scheme: "basic", csrf: true }, "none", true, true).csrf, false, "no auth, no token fetch");
  assert.equal(withScheme({ scheme: "basic", csrf: false }, "bearer", true, true).csrf, false, "an admin's off stays off");
  assert.equal(csrfApplies("none", true, false), false);
  assert.equal(csrfApplies("basic", false, false), false, "an API without writes needs no token");
  assert.equal(csrfApplies("basic", null, false), true, "entered by hand: writes may follow");
  const definition = { name: "SAP", servers: [], timeout_seconds: 30,
    auth: { scheme: "basic", csrf: { fetch: true, header: "x-csrf-token", fetch_path: "/sap/opu/odata/sap/API_X/" } } };
  const draft = definitionEditDraft(definition);
  assert.equal(draft.csrf, true);
  assert.deepEqual(definitionEditBody(definition, draft).auth.csrf,
    { fetch: true, header: "x-csrf-token", fetch_path: "/sap/opu/odata/sap/API_X/" }, "a save never drops the switch or its path");
  assert.equal(definitionEditBody(definition, { ...draft, csrf: false }).auth.csrf, undefined);
  assert.deepEqual(manualBody({ key: "s", name: "", servers: "", scheme: "basic", headerName: "", queryName: "", tokenUrl: "", scopes: "", timeout: "30", csrf: true }).auth,
    { scheme: "basic", csrf: { fetch: true, header: "x-csrf-token" } });
});

test("a $-parameter shows its wire name next to the alias; a plain one does not; a list alias is typed with commas", () => {
  const odataOp = op({ parameters: [{ name: "select", wire_name: "$select", in: "query", required: false, description: "", schema: { type: "array" } },
    { name: "top", wire_name: "$top", in: "query", required: false, description: "", schema: { type: "integer" } }] });
  assert.deepEqual(testBody(odataOp, { workspaceId: "", mode: "form", values: { select: "Product, ProductName", top: "2" }, json: "" }).body.arguments,
    { select: ["Product", "ProductName"], top: 2 }, "the model's alias names go out; the server sends $select=Product,ProductName");
  assert.equal(wireNameOf({ name: "select", wire_name: "$select" }), "$select");
  assert.equal(wireNameOf({ name: "group" }), null);
  assert.equal(wireNameOf({ name: "top", wire_name: "top" }), null);
});

test("the $batch refusal on enable and the CSRF refusals read as words at their field", () => {
  const batch = restErrorView(err(400, "This is an OData $batch operation, which Octryx does not run: a batch carries several requests past the per-call grants and audit. Enable the single operations instead."));
  assert.deepEqual(batch, { field: "enabled", text: "$batch is not supported. Enable the single operations instead." });
  assert.equal(restErrorView(err(400, "auth.csrf.fetch_path must be a path starting with '/'")).field, "csrf_fetch_path");
  assert.equal(restErrorView(err(400, "auth.csrf.header must name a token header")).field, "csrf_header");
  assert.equal(operationState({ enabled: false, grants: [], unsupported: "odata_batch" }).label, "$batch is not supported");
});

test("a refused server lands on its row, counting the entries of earlier lines", () => {
  const refused = restErrorView(Object.assign(err(422, "servers[1] has no host: 'https://:'"), { loc: ["body", "servers", 1] }));
  assert.deepEqual(refused, { field: "servers", index: 1, text: "This address has no host." });
  assert.equal(serverRowOfIndex("https://a.example\nhttps://:", 1), 1);
  assert.equal(serverRowOfIndex("https://a.example\n\nhttps://:", 1), 2, "a blank line sends nothing");
  assert.equal(serverRowOfIndex("https://a.example, https://b.example\nftp://c", 2), 1, "two servers on one line");
  assert.equal(serverRowOfIndex("https://a.example", 3), null);
});

test("calls are filtered by API and operation on the server; an operation without its API is ignored", () => {
  assert.equal(callsQuery({ definitionId: "", opId: "" }), "limit=200");
  assert.equal(callsQuery({ definitionId: "d1", opId: "o1" }, 50), "limit=50&definition_id=d1&op_id=o1");
  assert.equal(callsQuery({ definitionId: "", opId: "o1" }), "limit=200");
  assert.deepEqual(callsFilterFromSearch("?area=admin&tab=restApiCalls&rest_api=d1&rest_op=o1"), { definitionId: "d1", opId: "o1" });
  assert.deepEqual(callsFilterFromSearch("?rest_op=o1"), { definitionId: "", opId: "" });
});

// ---- OData preset as an API default, CSRF fetch path (backend) ----------------------------------------------

test("an operation's template: the API default, none or a template is sent as {preset}, by hand as the fields", () => {
  const inheriting = op({ preset: "odata_v2", preset_source: "definition", records_path: "d.results",
    pagination: { type: "next_url", next_path: "d.__next" } });
  const draft = operationDraft(inheriting);
  assert.equal(draft.presetChoice, "inherit", "an operation without own settings keeps following the default");
  assert.deepEqual(answerBody(draft), { preset: "inherit" }, "saving other fields does not pin the default");
  const context = { defaultPreset: "odata_v2", collection: true };
  assert.deepEqual(answerBody(choosePreset(draft, "none", context)), { preset: "none" });
  const v4 = choosePreset(draft, "odata_v4", context);
  assert.deepEqual(answerBody(v4), { preset: "odata_v4" });
  assert.equal(v4.recordsPath, "value", "the fields show what the template sets");
  const byHand = editAnswer(v4, { recordsPath: "d.items" });
  assert.equal(byHand.presetChoice, "", "an edit makes it 'by hand'");
  assert.deepEqual(answerBody(byHand), { records_path: "d.items", pagination: { type: "next_url", next_path: "@odata.nextLink" } });
  assert.equal(choosePreset(byHand, "inherit", context).recordsPath, "d.results", "back to the default shows its values");

  // What the server stored reads back as the choice.
  assert.equal(operationDraft(op({ preset: "odata_v4", preset_source: "operation", records_path: "value",
    pagination: { type: "next_url", next_path: "@odata.nextLink" } })).presetChoice, "odata_v4");
  assert.equal(operationDraft(op({ preset: "", preset_source: "operation" })).presetChoice, "none");
  assert.equal(operationDraft(op({ preset: "", preset_source: "operation", records_path: "items" })).presetChoice, "");
  assert.equal(operationDraft(op({ preset: "", preset_source: "none" })).presetChoice, "inherit");
});

test("the template in effect says where it comes from; a single-entity read has none", () => {
  assert.equal(presetInEffect(op({ preset: "odata_v2", preset_source: "definition" })), "OData v2 · From the API default");
  assert.equal(presetInEffect(op({ preset: "odata_v4", preset_source: "operation" })), "OData v4 · Set for this operation");
  assert.equal(presetInEffect(op({ preset: "", preset_source: "operation" })), "Own records path and pages · Set for this operation");
  assert.equal(presetInEffect(op({ preset: "", preset_source: "none" })), "None");
  assert.match(presetInEffect(op({ path: "/A_Product('{Product}')", preset_source: "none" })), /^Not applicable/);
  assert.equal(isCollectionRead({ method: "GET", path: "/A_Product" }), true);
  assert.equal(isCollectionRead({ method: "GET", path: "/A_Product(Product='{Product}')/" }), false);
  assert.equal(isCollectionRead({ method: "GET", path: "/tickets/{id}" }), false);
  assert.equal(isCollectionRead({ method: "GET", path: "/A_Product/$count" }), false);
  assert.equal(isCollectionRead({ method: "POST", path: "/A_Product" }), false);
  assert.deepEqual(presetOptions("odata_v2").map((entry) => entry.value), ["inherit", "none", "odata_v2", "odata_v2_offset", "odata_v4", ""]);
  assert.equal(presetOptions("")[0].label, "Use the API default (no template)");
});

test("the API's default template is sent with the details; an unknown one is refused at its field", () => {
  const definition = { name: "SAP", servers: [], timeout_seconds: 30, auth: { scheme: "none" }, default_preset: "odata_v2" };
  const draft = definitionEditDraft(definition);
  assert.equal(draft.defaultPreset, "odata_v2");
  assert.equal(definitionEditBody(definition, { ...draft, defaultPreset: "" }).default_preset, "");
  assert.equal("default_preset" in definitionEditBody({ auth: { scheme: "none" } },
    definitionEditDraft({ name: "x", servers: [], timeout_seconds: 30, auth: { scheme: "none" } })), false, "a definition without it gets none");
  const refused = restErrorView(Object.assign(err(422, "must be one of odata_v2, odata_v2_offset, odata_v4 or empty"), { field: "default_preset" }));
  assert.deepEqual(refused, { field: "default_preset", text: "Choose one of the offered templates, or no template." });
});

test("the CSRF option: header default x-csrf-token, a fetch path only when set", () => {
  assert.deepEqual(csrfBody({ csrfHeader: "", csrfFetchPath: "" }), { fetch: true, header: "x-csrf-token" });
  assert.deepEqual(csrfBody({ csrfHeader: " X-Token ", csrfFetchPath: " /sap/opu/odata/sap/API_X/ " }),
    { fetch: true, header: "X-Token", fetch_path: "/sap/opu/odata/sap/API_X/" });
  const definition = { name: "SAP", servers: [], timeout_seconds: 30, auth: { scheme: "basic", csrf: { fetch: true, header: "x-csrf-token" } } };
  const draft = definitionEditDraft(definition);
  assert.equal(draft.csrfFetchPath, "", "empty by default: the connection's base URL");
  assert.deepEqual(definitionEditBody(definition, { ...draft, csrfFetchPath: "/svc/" }).auth.csrf,
    { fetch: true, header: "x-csrf-token", fetch_path: "/svc/" });
  assert.deepEqual(definitionEditBody(definition, { ...draft, csrfFetchPath: "" }).auth.csrf, { fetch: true, header: "x-csrf-token" },
    "clearing the path sends none, so the base URL is used again");
});
