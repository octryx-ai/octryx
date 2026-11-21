// E2 (central configuration, approved): Admin › Connections. One page per connection with its uses,
// against the backend contract (plain UUID ids,
// intakes under uses.tickets, "needs approval" is a rule). Until the server has the endpoints (404) the page says
// so in one line and links today's pages — no stand-in data.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { ADMIN_AREA_CONFIGS, resolveAdminAreaTab } from "../../src/admin/config/adminPanelAreas.ts";
import { ADMIN_PAGE_PURPOSE } from "../../src/admin/config/pagePurpose.ts";
import { changesOf, draftOf, fieldErrorsOf } from "../../src/admin/components/connections/connectionDraft.ts";
import {
  isGitType,
  readConnectionTypes,
  scheduleOptions,
  scheduleText,
  scopeKeyOf,
  ticketStatesOf,
  splitValues,
  typeLabel,
} from "../../src/admin/components/connections/connectionTypes.ts";
import {
  availableInText,
  connectionAddress,
  deleteResultText,
  deviationText,
  intakeSyncText,
  readConnectionAddress,
  readConnectionDetail,
  readConnectionList,
  rulesHrefFor,
  usesText,
} from "../../src/admin/components/connections/connectionsModel.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));
const byId = (root, id) => root.find((node) => node.props["data-testid"] === id);
const allById = (root, id) => root.findAll((node) => node.props["data-testid"] === id);

const ID = "4f0c2a8e-1b7d-4c55-9e1a-2b3c4d5e6f70";
const LIST = { connections: [
  { id: ID, type: "jira", name: "Jira Cloud (octryx)", state: "ok", state_reason: null, last_tested_at: "2026-11-06T10:00:00+00:00",
    available_in: "selected", workspaces: [{ id: "ws_1", name: "Acme Orders" }], uses: { knowledge: true, tickets: true, agent_tools: "read" },
    owner: { kind: "platform" }, can_edit: true, deviation_count: 1, problems_count: 0 },
  { id: "9a8b7c6d-0000-4000-8000-000000000002", type: "bitbucket", name: "Bitbucket Shop", state: "failing",
    state_reason: "Sign-in fails: 401 Unauthorized", last_tested_at: null, available_in: "all", workspaces: [],
    uses: { knowledge: false, tickets: false, agent_tools: "write" }, owner: { kind: "platform" }, can_edit: false,
    deviation_count: 0, problems_count: 2 },
] };
const DETAIL = {
  id: ID, type: "jira", name: "Jira Cloud (octryx)", state: "ok", state_reason: null, last_tested_at: "2026-11-06T10:00:00+00:00",
  access: { base_url: "https://your-site.atlassian.net", auth: "api_token", account: "bot@octryx.test", secret_set: true,
    fields: { base_url: "https://your-site.atlassian.net", jira_auth_mode: "api_token", account: "bot@octryx.test" },
    secrets: { api_token: true } },
  available_in: "selected", workspaces: [{ id: "ws_1", name: "Acme Orders" }], owner: { kind: "platform" }, can_edit: true,
  uses: {
    knowledge: { enabled: true, scope: { projects: ["BRD"] }, schedule: "every_15_min", last_sync_at: "2026-11-06T09:00:00+00:00",
      last_sync_state: "ok", items: 1234 },
    tickets: { enabled: true, filter: "project = BRD", schedule: "every_15_min", scope: { projects: ["BRD"] },
      status_map: [{ source: "In Überprüfung", ours: "in_review" }],
      write_back: { enabled: true, transitions: [{ ours: "done", source: "Done" }] },
      intakes: [{ intake_id: "int_1", name: "BRD intake", workspace: { id: "ws_1", name: "Acme Orders" }, enabled: true, schedule: "every_15_min",
        last_sync_at: "2026-11-06T09:30:00+00:00", last_sync_status: "ok" }] },
    agent_tools: { level: "read", tools: [{ name: "jira_get_issue", level: "read" }] },
  },
  deviations: [{ workspace: { id: "ws_2", name: "Test" }, fields: { knowledge: { scope: { projects: ["BRD-sub"] } } } }],
  recent_errors: [{ at: "2026-11-06T08:00:00+00:00", use: "tickets", message: "401 Unauthorized" }],
};
const TYPES = [
  { type: "jira", label: "Jira", auth_kinds: ["api_token", "oauth"], uses: ["knowledge", "tickets", "agent_tools"],
    scope_key: "projects",
    ticket_states: [{ key: "in_review", label: "In review" }, { key: "done", label: "Done" }, { key: "open", label: "Open" }],
    testable: true,
    access_fields: [{ key: "base_url", label: "Site address", required: true, secret: false, kind: "url", options: [] },
      { key: "jira_auth_mode", label: "Sign-in", required: true, secret: false, kind: "select", options: [] },
      { key: "account", label: "Account e-mail", required: true, secret: false, kind: "text", options: [] },
      { key: "api_token", label: "API token", required: true, secret: true, kind: "secret", options: [] },
      { key: "verify_tls", label: "Verify TLS", required: false, secret: false, kind: "bool", options: [] }] },
  { type: "github", label: "GitHub", auth_kinds: ["token"], uses: ["repositories", "agent_tools"], scope_key: null, testable: false,
    access_fields: [{ key: "token", label: "Access token", required: true, secret: true, kind: "secret", options: [] }] },
];
const PROJECTS = [{ id: "ws_1", name: "Acme Orders" }, { id: "ws_2", name: "Test" }];

function makeLoader(stubs, sandbox) {
  const cache = new Map();
  const load = (file) => {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    vm.runInNewContext(output, { exports, ...sandbox, require: (name) => resolve(name, path.dirname(file)) });
    return exports;
  };
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (!name.startsWith(".")) return require(name);
    const base = path.resolve(dir, name);
    const file = [".tsx", ".ts"].map((ext) => base + ext).find((candidate) => fs.existsSync(candidate));
    return load(file);
  };
  return (relative) => load(path.join(SRC, relative));
}

const reply = (status, body) => ({ status, ok: status >= 200 && status < 300, json: async () => body });

function server(overrides = {}) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const method = init.method ?? "GET";
    calls.push({ url, method, body: init.body ? JSON.parse(init.body) : null });
    const key = `${method} ${url}`;
    if (overrides[key]) return overrides[key]();
    if (key === "GET /api/v1/admin/connections") return reply(200, LIST);
    if (key === "GET /api/v1/admin/connection-types") return reply(200, TYPES);
    if (key === `GET /api/v1/admin/connections/${ID}`) return reply(200, DETAIL);
    if (key === `POST /api/v1/admin/connections/${ID}/test`) return reply(200, { state: "failing", state_reason: "Tickets: 401", tested_at: "2026-11-06T11:00:00+00:00",
      checks: [{ use: "access", ok: true, message: "" }, { use: "tickets", ok: false, message: "401 Unauthorized" }] });
    if (key === `DELETE /api/v1/workspaces/ws_2/connections/${ID}/deviation`) return reply(200, { effective: {}, deviation: null });
    if (key === "POST /api/v1/secure-work/workspaces/ws_1/intake/int_1/sync") return reply(200, { state: "completed", intake_id: "int_1", summary: { updated: 3 } });
    return reply(404, { detail: "Not Found" });
  };
  return { fetch, calls };
}

const sandbox = (srv, search = "") => {
  const history = { state: null, replaced: [], replaceState(_state, _title, href) { history.replaced.push(href); } };
  return {
    fetch: srv.fetch, JSON, Date, Math, Number, Object, Array, String, Boolean, Error, Promise, Set, Map, console,
    URLSearchParams, encodeURIComponent, setTimeout, clearTimeout,
    window: { innerWidth: 1400, location: { search, pathname: "/chat" }, history, addEventListener() {}, removeEventListener() {} },
    document: { addEventListener() {}, removeEventListener() {}, activeElement: null },
  };
};

async function render(srv, search = "") {
  const opened = [];
  const box = sandbox(srv, search);
  const load = makeLoader({ "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) } }, box);
  const { ConnectionsPage } = load("admin/components/connections/ConnectionsPage.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(ConnectionsPage, { projects: PROJECTS }), { createNodeMock: () => ({ focus() {} }) }); });
  await act(async () => {});
  await act(async () => {});
  return { view, opened, history: box.window.history };
}

test("Connections is the Connections entry's main view, with one purpose sentence", () => {
  const entry = ADMIN_ENTRIES.find((item) => item.label === "Connections");
  assert.equal(entry.tab, "adminConnections");
  assert.equal(entry.views[0].pages[0].tab, "adminConnections");
  assert.equal(resolveAdminAreaTab("admin", "adminConnections"), "adminConnections");
  assert.ok(ADMIN_PAGE_PURPOSE.adminConnections);
  const pages = entry.views.flatMap((view) => (view.pages ?? []).map((page) => page.tab));
  assert.ok(pages.includes("mcp"), "mcp stays reachable as a view");
  // The connector settings page is no view of its own; it is reachable inside Connections.
  assert.ok(!entry.views.some((view) => view.key === "connectors"), "no Connectors (current) segment");
  assert.deepEqual(entry.views[0].pages[0].also, ["connectors"]);
});

test("the model reads the contract and words it", () => {
  const [jira, bitbucket] = readConnectionList(LIST);
  assert.equal(jira.id, ID);
  assert.equal(availableInText(jira.availableIn, jira.workspaces), "Acme Orders");
  assert.equal(availableInText("all", []), "All workspaces");
  assert.equal(availableInText("selected", [{ id: "a", name: "A" }, { id: "b", name: "B" }, { id: "c", name: "C" }]), "3 workspaces");
  assert.equal(usesText(jira.uses), "Knowledge · Tickets · Tools: read");
  assert.equal(bitbucket.canEdit, false);
  const detail = readConnectionDetail(DETAIL);
  assert.equal(detail.tickets.intakes[0].id, "int_1");
  assert.equal(detail.access.secretSet, true);
  assert.equal(JSON.stringify(detail).includes("secret\""), false, "no secret value is kept");
  assert.equal(deviationText(detail.deviations[0].fields), "Knowledge scope projects: BRD-sub");
  assert.equal(rulesHrefFor(ID), "/chat?area=admin&tab=policies", "the rule list per connection is not served yet");
  assert.deepEqual(readConnectionAddress(connectionAddress("?area=admin&tab=adminConnections", ID, true)), { id: ID, page: true });
  assert.equal(intakeSyncText(409, { detail: { code: "intake_not_enabled" } }), "This intake is switched off; switch it on first.");
  assert.equal(intakeSyncText(502, null), "The source did not answer; try again later.");
});

test("types come from the server's descriptors; schedules are the server's presets", () => {
  const types = readConnectionTypes(TYPES);
  assert.deepEqual(types.map((entry) => entry.type), ["jira", "github"]);
  assert.equal(typeLabel("jira", types), "Jira");
  assert.equal(typeLabel("kubernetes", types), "Kubernetes", "unknown types read as words, no fixed list");
  assert.equal(types[0].accessFields.find((field) => field.key === "api_token").secret, true);
  assert.equal(scopeKeyOf("jira", types), "projects", "scope_key from the descriptor");
  assert.equal(scopeKeyOf("github", types), "", "scope_key null: no scope editor");
  assert.equal(scopeKeyOf("confluence"), "", "no guessing without a descriptor");
  assert.deepEqual(ticketStatesOf("jira", types).map((state) => state.key), ["in_review", "done", "open"]);
  assert.deepEqual(ticketStatesOf("github", types), []);
  assert.equal(isGitType("github", types), true);
  assert.equal(isGitType("jira", types), false);
  assert.deepEqual(scheduleOptions("hourly"), ["manual", "every_15_min", "hourly", "every_4_hours", "daily_0600", "custom"]);
  assert.deepEqual(scheduleOptions("custom"), ["manual", "every_15_min", "hourly", "every_4_hours", "daily_0600", "custom"]);
  assert.equal(scheduleOptions("").includes("every_5_min"), false);
  assert.equal(scheduleText("daily_0600"), "Daily at 06:00");
  assert.equal(scheduleText("off"), "Manual");
  assert.deepEqual(splitValues(" TEAM, OPS;TEAM\nDOC "), ["TEAM", "OPS", "DOC"]);
});

test("a save sends only what changed; a new secret only when typed; refusals name their field", () => {
  const before = draftOf(readConnectionDetail(DETAIL), "projects");
  assert.deepEqual(changesOf(before, before), {});
  assert.deepEqual(changesOf(before, { ...before, name: "Jira (team) ", secrets: { api_token: "s3cret" } }),
    { name: "Jira (team)", access: { api_token: "s3cret" } });
  assert.deepEqual(changesOf(before, { ...before, access: { ...before.access, base_url: "https://new.atlassian.net " } }),
    { access: { base_url: "https://new.atlassian.net" } });
  assert.equal(before.knowledgeScope, "BRD");
  assert.deepEqual(changesOf(before, { ...before, knowledgeScope: "BRD, OPS" }, { projects: ["BRD"], labels: ["x"] }),
    { uses: { knowledge: { scope: { projects: ["BRD", "OPS"], labels: ["x"] } } } }, "the whole scope goes, other keys kept");
  assert.deepEqual(changesOf(before, { ...before, ticketsFilter: "project = OPS", statusMap: [...before.statusMap, { source: "Done", ours: "done" }, { source: "", ours: "" }] }),
    { uses: { tickets: { filter: "project = OPS", status_map: [{ source: "In Überprüfung", ours: "in_review" }, { source: "Done", ours: "done" }] } } },
    "arrays replace as a whole; empty rows are dropped");
  assert.equal("transitions" in before, false, "write-back is the workflow's: not part of the draft");
  assert.deepEqual(changesOf(before, { ...before, access: { ...before.access, verify_tls: "false" } }, null, readConnectionTypes(TYPES)[0].accessFields),
    { access: { verify_tls: false } }, "a bool field goes as a boolean");
  assert.deepEqual(fieldErrorsOf({ detail: { code: "scope_outside_connection" } }),
    { field: "uses.knowledge.scope", message: "This is outside what the connection may read.", code: "scope_outside_connection" });
  assert.deepEqual(changesOf(before, { ...before, availableIn: "all" }), { available_in: "all", workspaces: [] });
  assert.deepEqual(changesOf(before, { ...before, toolLevel: "write" }), { uses: { agent_tools: { level: "write" } } });
  assert.deepEqual(fieldErrorsOf({ detail: { code: "deviation_not_narrower", field: "uses.knowledge.schedule" } }),
    { field: "uses.knowledge.schedule", message: "A workspace may only narrow this connection, not widen it.", code: "deviation_not_narrower" });
});

test("rendered list: full-width table with state, available in, uses, deviations; read-only rows marked", async () => {
  const { view } = await render(server());
  const rows = byId(view.root, "connections-table").findAll((node) => node.type === "tr");
  assert.equal(rows.length, 3, "header and two connections");
  assert.match(text(rows[1]), /Jira Cloud \(octryx\)JiraWorkingAcme OrdersKnowledge · Tickets · Tools: read1/);
  assert.match(text(rows[2]), /Bitbucket Shop · read onlyBitbucketFailingAll workspacesTools: write—Never/);
  assert.ok(byId(view.root, "connections-add"), "Add connection is the header's primary action");
  act(() => view.unmount());
});

test("404: the page says the connections arrive with the central configuration and links today's pages", async () => {
  const { view, opened } = await render(server({ "GET /api/v1/admin/connections": () => reply(404, { detail: "Not Found" }) }));
  assert.match(text(byId(view.root, "connections-pending-line")), /^Connections arrive with the central configuration\./);
  assert.equal(allById(view.root, "connections-table").length, 0, "no stand-in data");
  act(() => view.root.findAll((node) => node.type === "button" && text(node) === "Connectors")[0].props.onClick());
  assert.deepEqual(opened, ["connectors"]);
  act(() => view.unmount());
});

test("rendered detail: tabs, test checks, deviation reset, sync now, approval rules link", async () => {
  const srv = server();
  const { view, history } = await render(srv, `?area=admin&tab=adminConnections&connection=${ID}`);
  const panel = byId(view.root, "connection-panel");
  assert.match(text(byId(panel, "connection-state")), /Working/);
  assert.ok(allById(panel, "connection-panel-open-page").length, "Open as page");
  await act(async () => { byId(panel, "connection-test").props.onClick(); });
  assert.match(text(byId(view.root, "connection-test-checks")), /Failed tickets: 401 Unauthorized/);
  assert.match(text(byId(view.root, "connection-state")), /Failing/);
  const tab = (key) => view.root.find((node) => node.props.role === "tab" && node.props.id === `connection-tab-tab-${key}`);
  await act(async () => { tab("tickets").props.onClick(); });
  assert.equal(byId(view.root, "connection-status-map-source-0").props.value, "In Überprüfung");
  await act(async () => { byId(view.root, "intake-sync-int_1").props.onClick(); });
  await act(async () => {});
  assert.match(text(byId(view.root, "connection-intakes")), /Synced: 3 items changed\./);
  await act(async () => { tab("tools").props.onClick(); });
  assert.equal(byId(view.root, "connection-approval-rules").props.href, "/chat?area=admin&tab=policies");
  await act(async () => { tab("deviations").props.onClick(); });
  await act(async () => { byId(view.root, `deviation-reset-ws_2`).props.onClick(); });
  await act(async () => {});
  assert.ok(srv.calls.some((call) => call.method === "DELETE" && call.url.endsWith(`/workspaces/ws_2/connections/${ID}/deviation`)));
  await act(async () => { byId(view.root, "connection-panel-close").props.onClick(); });
  assert.equal(history.replaced.at(-1), "/chat?area=admin&tab=adminConnections", "closing drops ?connection");
  act(() => view.unmount());
});

test("Connector settings: header button and the connection's ⋯ menu open today's connector page", async () => {
  const { view, opened, history } = await render(server(), `?area=admin&tab=adminConnections&connection=${ID}`);
  const more = view.root.find((node) => node.type === "button" && node.props["aria-label"] === `More actions for ${DETAIL.name}`);
  act(() => more.props.onClick({ currentTarget: { getBoundingClientRect: () => ({ bottom: 0, right: 0 }) } }));
  act(() => byId(view.root, "connection-connector-settings").props.onClick());
  assert.deepEqual(opened, ["connectors"]);
  assert.equal(history.replaced.at(-1), "/chat?area=admin&tab=adminConnections&connector=jira", "names the type, drops ?connection");
  act(() => byId(view.root, "connections-connector-settings").props.onClick());
  assert.deepEqual(opened, ["connectors", "connectors"]);
  act(() => view.unmount());
});

test("rendered detail: Available in editor saves a partial PUT; a 422 shows at its field", async () => {
  const srv = server({ [`PUT /api/v1/admin/connections/${ID}`]: () => reply(422, { detail: { code: "invalid_workspaces", field: "workspaces",
    message: "Test is not a workspace you manage." } }) });
  const { view } = await render(srv, `?connection=${ID}`);
  const editor = byId(view.root, "connection-available-in");
  await act(async () => { byId(editor, "connection-workspace-ws_2").props.onChange(); });
  await act(async () => { byId(view.root, "connection-save").props.onClick(); });
  await act(async () => {});
  const put = srv.calls.find((call) => call.method === "PUT");
  assert.deepEqual(put.body, { available_in: "selected", workspaces: ["ws_1", "ws_2"] });
  assert.match(text(byId(view.root, "field-error-workspaces")), /Test is not a workspace you manage\./);
  act(() => view.unmount());
});

test("rendered detail: a platform connection is read-only for a workspace admin (can_edit false)", async () => {
  const srv = server({ [`GET /api/v1/admin/connections/${ID}`]: () => reply(200, { ...DETAIL, can_edit: false }) });
  const { view } = await render(srv, `?connection=${ID}`);
  assert.ok(byId(view.root, "connection-read-only"));
  assert.equal(allById(view.root, "connection-save").length, 0, "no save");
  assert.equal(view.root.findAll((node) => String(node.props["data-testid"] ?? "").startsWith("connection-secret")).length, 0, "no secret field");
  act(() => view.unmount());
});

test("rendered Add connection: the descriptor's fields, required marks, secrets as passwords, then POST", async () => {
  const srv = server({ "POST /api/v1/admin/connections": () => reply(201, { ...DETAIL, id: "new-id" }) });
  const { view } = await render(srv);
  await act(async () => { byId(view.root, "connections-add").props.onClick(); });
  assert.match(text(byId(view.root, "connection-add-hint")), /Choose a type\./);
  const options = byId(view.root, "connection-add-type").findAll((node) => node.type === "option").map(text);
  assert.deepEqual(options, ["Choose…", "Jira", "GitHub"], "the server's types, no fixed list");
  await act(async () => { byId(view.root, "connection-add-type").props.onChange({ target: { value: "jira" } }); });
  await act(async () => { byId(view.root, "connection-add-name").props.onChange({ target: { value: "Jira (team)" } }); });
  // The hint names the fields as the form labels them, in their own case.
  assert.match(text(byId(view.root, "connection-add-hint")), /Fill in Site address, Account e-mail, API token\./);
  assert.equal(byId(view.root, "connection-secret-api_token").props.type, "password");
  assert.match(text(view.root.find((node) => node.props["data-field"] === "access.api_token")), /API token \(required\)/);
  await act(async () => { byId(view.root, "connection-access-base_url").props.onChange({ target: { value: " https://team.atlassian.net " } }); });
  await act(async () => { byId(view.root, "connection-access-account").props.onChange({ target: { value: "bot@team.test" } }); });
  await act(async () => { byId(view.root, "connection-secret-api_token").props.onChange({ target: { value: "tok" } }); });
  await act(async () => { byId(view.root, "connection-add-submit").props.onClick(); });
  await act(async () => {});
  const post = srv.calls.find((call) => call.method === "POST" && call.url === "/api/v1/admin/connections");
  assert.deepEqual(post.body, { type: "jira", name: "Jira (team)",
    access: { jira_auth_mode: "api_token", base_url: "https://team.atlassian.net", account: "bot@team.test", api_token: "tok" },
    available_in: "selected", workspaces: [] }, "the sign-in field preset to the first auth kind; access keyed like access_fields");
  act(() => view.unmount());
});

test("rendered Add connection without descriptors says so and cannot submit", async () => {
  const srv = server({ "GET /api/v1/admin/connection-types": () => reply(404, { detail: "Not Found" }) });
  const { view } = await render(srv);
  await act(async () => { byId(view.root, "connections-add").props.onClick(); });
  assert.ok(byId(view.root, "connection-add-no-types"));
  assert.equal(byId(view.root, "connection-add-submit").props.disabled, true);
  act(() => view.unmount());
});

test("rendered detail: uses are editable and saved as one partial PUT; the answer is used as is", async () => {
  const saved = { ...DETAIL, uses: { ...DETAIL.uses, tickets: { ...DETAIL.uses.tickets, filter: "project = OPS" } } };
  const srv = server({ [`PUT /api/v1/admin/connections/${ID}`]: () => reply(200, saved) });
  const { view } = await render(srv, `?connection=${ID}`);
  const tab = (key) => view.root.find((node) => node.props.role === "tab" && node.props.id === `connection-tab-tab-${key}`);
  await act(async () => { tab("knowledge").props.onClick(); });
  assert.equal(byId(view.root, "connection-knowledge-scope").props.value, "BRD", "the scope as a list, never JSON");
  await act(async () => { byId(view.root, "connection-knowledge-scope").props.onChange({ target: { value: "BRD, OPS" } }); });
  const schedule = byId(view.root, "schedule-uses.knowledge.schedule");
  assert.deepEqual(schedule.findAll((node) => node.type === "option").map(text),
    ["Manual", "Every 15 minutes", "Hourly", "Every 4 hours", "Daily at 06:00", "Custom"]);
  await act(async () => { tab("tickets").props.onClick(); });
  await act(async () => { byId(view.root, "connection-tickets-filter").props.onChange({ target: { value: "project = OPS" } }); });
  await act(async () => { byId(view.root, "connection-status-map-add").props.onClick(); });
  await act(async () => { byId(view.root, "connection-status-map-source-1").props.onChange({ target: { value: "Done" } }); });
  const ours = byId(view.root, "connection-status-map-ours-1");
  assert.equal(ours.type, "select", "\"Here\" is a choice of our ticket states");
  assert.deepEqual(ours.findAll((node) => node.type === "option").map(text), ["Choose a state", "In review", "Done", "Open"]);
  await act(async () => { ours.props.onChange({ target: { value: "done" } }); });
  assert.equal(allById(view.root, "connection-write-back-remove-0").length, 0, "write-back is read-only here");
  assert.match(byId(view.root, "connection-write-back-link").props.href, /work_view=writeback&workspace_id=ws_1/);
  const gets = srv.calls.filter((call) => call.method === "GET" && call.url.endsWith(ID)).length;
  await act(async () => { byId(view.root, "connection-save").props.onClick(); });
  await act(async () => {});
  const put = srv.calls.find((call) => call.method === "PUT");
  assert.deepEqual(put.body, { uses: {
    knowledge: { scope: { projects: ["BRD", "OPS"] } },
    tickets: { filter: "project = OPS",
      status_map: [{ source: "In Überprüfung", ours: "in_review" }, { source: "Done", ours: "done" }] } } },
    "write-back is never sent");
  assert.equal(srv.calls.filter((call) => call.method === "GET" && call.url.endsWith(ID)).length, gets, "PUT's full detail is used, no reload");
  assert.match(text(byId(view.root, "connection-notice")), /Changes saved\./);
  act(() => view.unmount());
});

test("rendered detail: a scope outside the connection is refused at the scope field", async () => {
  const srv = server({ [`PUT /api/v1/admin/connections/${ID}`]: () => reply(422, { detail: { code: "scope_outside_connection",
    message: "OPS is not readable with this account." } }) });
  const { view } = await render(srv, `?connection=${ID}`);
  const tab = (key) => view.root.find((node) => node.props.role === "tab" && node.props.id === `connection-tab-tab-${key}`);
  await act(async () => { tab("knowledge").props.onClick(); });
  await act(async () => { byId(view.root, "connection-knowledge-scope").props.onChange({ target: { value: "OPS" } }); });
  await act(async () => { byId(view.root, "connection-save").props.onClick(); });
  await act(async () => {});
  assert.match(text(byId(view.root, "field-error-uses.knowledge.scope")), /OPS is not readable with this account\./);
  act(() => view.unmount());
});

test("a custom schedule sends its cron; an invalid cron and an unknown state are refused at their field", async () => {
  const before = draftOf(readConnectionDetail(DETAIL), "projects");
  assert.deepEqual(changesOf(before, { ...before, ticketsSchedule: "custom", ticketsCron: " */30 * * * * " }),
    { uses: { tickets: { schedule: "custom", schedule_cron: "*/30 * * * *" } } });
  const custom = { ...before, ticketsSchedule: "custom", ticketsCron: "*/30 * * * *" };
  assert.deepEqual(changesOf(custom, { ...custom, ticketsCron: "0 * * * *" }),
    { uses: { tickets: { schedule: "custom", schedule_cron: "0 * * * *" } } });
  assert.deepEqual(changesOf(custom, { ...custom, ticketsSchedule: "hourly" }), { uses: { tickets: { schedule: "hourly" } } });
  assert.deepEqual(fieldErrorsOf({ detail: { code: "status_unknown" } }).field, "uses.tickets.status_map");

  const srv = server({ [`PUT /api/v1/admin/connections/${ID}`]: () => reply(422, { detail: { code: "schedule_cron_invalid",
    field: "uses.tickets.schedule_cron", message: "Runs more often than every 15 minutes." } }) });
  const { view } = await render(srv, `?connection=${ID}`);
  const tab = (key) => view.root.find((node) => node.props.role === "tab" && node.props.id === `connection-tab-tab-${key}`);
  await act(async () => { tab("tickets").props.onClick(); });
  await act(async () => { byId(view.root, "schedule-uses.tickets.schedule").props.onChange({ target: { value: "custom" } }); });
  const cron = byId(view.root, "schedule-cron-uses.tickets.schedule");
  assert.equal(cron.props.placeholder, "*/30 * * * *");
  await act(async () => { cron.props.onChange({ target: { value: "*/5 * * * *" } }); });
  await act(async () => { byId(view.root, "connection-save").props.onClick(); });
  await act(async () => {});
  assert.deepEqual(srv.calls.find((call) => call.method === "PUT").body,
    { uses: { tickets: { schedule: "custom", schedule_cron: "*/5 * * * *" } } });
  assert.match(text(byId(view.root, "field-error-uses.tickets.schedule_cron")), /every 15 minutes/);
  act(() => view.unmount());

  const srv2 = server({ [`PUT /api/v1/admin/connections/${ID}`]: () => reply(422, { detail: { code: "status_unknown",
    field: "uses.tickets.status_map[0].ours", message: "Choose one of our ticket states." } }) });
  const second = await render(srv2, `?connection=${ID}`);
  const tab2 = (key) => second.view.root.find((node) => node.props.role === "tab" && node.props.id === `connection-tab-tab-${key}`);
  await act(async () => { tab2("tickets").props.onClick(); });
  await act(async () => { byId(second.view.root, "connection-status-map-ours-0").props.onChange({ target: { value: "open" } }); });
  await act(async () => { byId(second.view.root, "connection-save").props.onClick(); });
  await act(async () => {});
  assert.match(text(byId(second.view.root, "field-error-uses.tickets.status_map")), /^Row 1: Choose one of our ticket states\./);
  act(() => second.view.unmount());
});

test("rendered detail: a workspace admin may reset their own deviation on a platform connection", async () => {
  const detail = { ...DETAIL, can_edit: false, deviations: [
    { workspace: { id: "ws_2", name: "Test" }, fields: { tickets: { schedule: "manual" } }, can_edit: true },
    { workspace: { id: "ws_3", name: "Other" }, fields: { tickets: { schedule: "manual" } }, can_edit: false },
  ] };
  const srv = server({ [`GET /api/v1/admin/connections/${ID}`]: () => reply(200, detail) });
  const { view } = await render(srv, `?connection=${ID}`);
  const tab = (key) => view.root.find((node) => node.props.role === "tab" && node.props.id === `connection-tab-tab-${key}`);
  await act(async () => { tab("deviations").props.onClick(); });
  assert.ok(byId(view.root, "deviation-reset-ws_2"), "own workspace: Reset");
  assert.equal(allById(view.root, "deviation-reset-ws_3").length, 0, "another workspace: no Reset");
  act(() => view.unmount());
});

test("backend shapes: bare type array, access.fields and per-field secrets, intake names, delete answers", () => {
  assert.deepEqual(readConnectionTypes({ types: TYPES }), [], "only the bare array the endpoint answers");
  const [jira, github] = readConnectionTypes(TYPES);
  assert.equal(jira.testable, true);
  assert.equal(github.testable, false);
  assert.equal(jira.accessFields.find((field) => field.key === "api_token").secret, true, "kind secret is a secret");
  const detail = readConnectionDetail(DETAIL);
  assert.deepEqual(detail.access.values, { base_url: "https://your-site.atlassian.net", jira_auth_mode: "api_token", account: "bot@octryx.test" });
  assert.deepEqual(detail.access.secrets, { api_token: true });
  assert.equal(detail.tickets.intakes[0].name, "BRD intake");
  assert.deepEqual(deleteResultText(200, { status: "deleted", id: ID }), { ok: true, text: "The connection was deleted." });
  assert.deepEqual(deleteResultText(409, { detail: { code: "connection_in_use", uses: [{ use: "knowledge", id: "k1", name: "Confluence RS", workspace_id: "ws_1" }] } }),
    { ok: false, text: "Still used by Knowledge: Confluence RS; remove or move these uses first." });
  assert.equal(fieldErrorsOf({ detail: { code: "write_back_on_workflow" } }).message, "Write-back is set in the Workspace's work item workflow, not here.");
});

test("rendered detail: secrets show set per field; Test hidden for untestable types; no switch-over note; delete in use", async () => {
  const srv = server({ [`DELETE /api/v1/admin/connections/${ID}`]: () => reply(409, { detail: { code: "connection_in_use",
    message: "The connection is still used.", uses: [{ use: "tickets", id: "int_1", name: "BRD intake", workspace_id: "ws_1" }] } }) });
  const { view } = await render(srv, `?connection=${ID}`);
  // Connections are used by agents, Knowledge sync and intakes since E2 step 2: no note says otherwise.
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "connections-switch-note").length, 0);
  // A stored secret is kept when left empty: replacing it is not required, and the field says so once.
  const replace = view.root.find((node) => node.props["data-field"] === "access.api_token");
  assert.match(text(replace), /^Replace API token$/);
  assert.equal(byId(view.root, "connection-secret-api_token").props.placeholder, "Stored · leave empty to keep it");
  assert.equal(byId(view.root, "connection-access-jira_auth_mode").type, "select", "the sign-in field is a select of the auth kinds");
  // Delete is the last item of the header's ⋯ menu, never a footer button; Save changes is the footer's only action.
  const footerDelete = view.root.findAll((node) => node.type === "button" && text(node) === "Delete…" && node.props.className?.includes("action-btn"));
  assert.equal(footerDelete.length, 0, "no Delete button in the footer");
  const more = view.root.find((node) => node.type === "button" && node.props["aria-label"] === `More actions for ${DETAIL.name}`);
  act(() => more.props.onClick({ currentTarget: { getBoundingClientRect: () => ({ bottom: 0, right: 0 }) } }));
  const items = view.root.findAll((node) => node.props.role === "menuitem").map(text);
  assert.deepEqual(items, ["Connector settings", "Delete…"]);
  await act(async () => { byId(view.root, "connection-delete").props.onClick(); });
  const confirmButton = view.root.findAll((node) => node.type === "button" && text(node) === `Delete ${DETAIL.name}`)[0];
  await act(async () => { confirmButton.props.onClick(); });
  await act(async () => {});
  assert.ok(srv.calls.some((call) => call.method === "DELETE" && call.url === `/api/v1/admin/connections/${ID}`));
  assert.ok(view.root.findAll((node) => typeof node.children?.[0] === "string" && /Still used by Tickets: BRD intake/.test(node.children[0])).length,
    "the uses that block the delete are named");
  act(() => view.unmount());

  const gh = { ...DETAIL, id: "gh-1", type: "github", access: { fields: {}, secrets: { token: true }, secret_set: true } };
  const srv2 = server({ "GET /api/v1/admin/connections/gh-1": () => reply(200, gh) });
  const second = await render(srv2, "?connection=gh-1");
  assert.equal(allById(second.view.root, "connection-test").length, 0, "testable false: no Test");
  act(() => second.view.unmount());
});

// Only the chosen sign-in kind's fields; errors as sentences, old ones
// under "Earlier".
import { visibleAccessFields } from "../../src/admin/components/connections/authFields.ts";
import { errorSentence, recentErrorCount, splitErrors } from "../../src/admin/components/connections/connectionErrors.ts";
import { ADMIN_ENTRIES } from "../../src/admin/config/adminEntries.ts";

const field = (key, extra = {}) => ({ key, label: key, required: false, secret: false, kind: "text", options: [], authKinds: [], ...extra });
const JIRA_FIELDS = [field("jira_url", { kind: "url" }), field("jira_auth_mode", { kind: "select" }), field("jira_email"),
  field("jira_token", { secret: true }), field("jira_username"), field("jira_password", { secret: true }),
  field("jira_oidc_token_url"), field("jira_oidc_client_id"), field("jira_oidc_client_secret", { secret: true }),
  field("jira_oidc_scope"), field("jira_oidc_audience"), field("jira_oidc_client_auth")];
const keys = (fields) => fields.map((item) => item.key);

test("Only the chosen sign-in kind's access fields show; switching shows the matching ones", () => {
  assert.deepEqual(keys(visibleAccessFields("jira", JIRA_FIELDS, { jira_auth_mode: "cloud_api_token" })),
    ["jira_url", "jira_auth_mode", "jira_email", "jira_token"]);
  assert.deepEqual(keys(visibleAccessFields("jira", JIRA_FIELDS, { jira_auth_mode: "basic" })),
    ["jira_url", "jira_auth_mode", "jira_username", "jira_password"]);
  assert.deepEqual(keys(visibleAccessFields("jira", JIRA_FIELDS, { jira_auth_mode: "oidc_client_credentials" })),
    ["jira_url", "jira_auth_mode", "jira_oidc_token_url", "jira_oidc_client_id", "jira_oidc_client_secret",
      "jira_oidc_scope", "jira_oidc_audience", "jira_oidc_client_auth"]);
  assert.deepEqual(keys(visibleAccessFields("jira", JIRA_FIELDS, {})), ["jira_url", "jira_auth_mode"], "no kind yet: only the choice");
  const marked = [field("x_auth_mode", { kind: "select" }), field("a", { authKinds: ["one"] }), field("b", { authKinds: ["two"] }), field("c")];
  assert.deepEqual(keys(visibleAccessFields("other", marked, { x_auth_mode: "two" })), ["x_auth_mode", "b", "c"], "server marks win");
  assert.deepEqual(keys(visibleAccessFields("unknown", [field("token", { secret: true })], {})), ["token"]);
});

test("ServiceNow: the API style is a select; the Scripted REST paths and page size show only for scripted", () => {
  const [sn] = readConnectionTypes([{ type: "servicenow", label: "ServiceNow", auth_kinds: ["basic"], access_fields: [
    { key: "servicenow_url", kind: "url" }, { key: "servicenow_auth_mode", kind: "select" },
    { key: "servicenow_api_style", kind: "select", options: ["table", "scripted"] },
    { key: "servicenow_incidents_path", kind: "text", placeholder: "/api/<namespace>/<api>/incidents" },
    { key: "servicenow_changes_path", kind: "text" }, { key: "servicenow_journal_path", kind: "text" },
    { key: "servicenow_page_size", kind: "int", placeholder: "100" }] }]);
  const shown = (values) => keys(visibleAccessFields("servicenow", sn.accessFields, { servicenow_auth_mode: "basic", ...values }));
  const always = ["servicenow_url", "servicenow_auth_mode", "servicenow_api_style"];
  assert.deepEqual(shown({}), always, "no style is the Table API");
  assert.deepEqual(shown({ servicenow_api_style: "table" }), always);
  assert.deepEqual(shown({ servicenow_api_style: "scripted" }), [...always, "servicenow_incidents_path",
    "servicenow_changes_path", "servicenow_journal_path", "servicenow_page_size"]);
  assert.equal(sn.accessFields[3].placeholder, "/api/<namespace>/<api>/incidents");
  const before = draftOf(readConnectionDetail({ ...DETAIL, access: { fields: { servicenow_api_style: "table" }, secrets: {} } }));
  const after = { ...before, access: { ...before.access, servicenow_api_style: "scripted",
    servicenow_incidents_path: "/api/x/y/incidents", servicenow_page_size: "50" } };
  assert.deepEqual(changesOf(before, after, null, sn.accessFields).access, { servicenow_api_style: "scripted",
    servicenow_incidents_path: "/api/x/y/incidents", servicenow_page_size: 50 }, "the page size goes as a number");
});

test("Errors read as one sentence (code as tooltip); errors before the last successful test are Earlier", () => {
  assert.deepEqual(errorSentence("jql_invalid"), { sentence: "The ticket filter is not valid JQL.", code: "jql_invalid" });
  assert.equal(errorSentence("scope_not_allowed").sentence, "The token lacks permission for this scope.");
  assert.equal(errorSentence("source_unauthorized").sentence, "The source refused the credentials.");
  assert.equal(errorSentence("some_new_code").sentence, "The source reported an error.", "unknown codes never raw");
  assert.deepEqual(errorSentence("Sign-in fails: 401 Unauthorized"), { sentence: "Sign-in fails: 401 Unauthorized", code: "" });
  assert.deepEqual(errorSentence("Jira refused the filter: unknown field 'foo'.", "jql_invalid"),
    { sentence: "Jira refused the filter: unknown field 'foo'.", code: "jql_invalid" }, "a server sentence wins, code as tooltip");
  assert.deepEqual(errorSentence("jql_invalid", "jql_invalid"), { sentence: "The ticket filter is not valid JQL.", code: "jql_invalid" });
  const errors = [{ at: "2026-11-06T12:00:00+00:00", use: "tickets", message: "jql_invalid" },
    { at: "2026-10-05T08:00:00+00:00", use: "tickets", message: "scope_not_allowed" }];
  const split = splitErrors(errors, "2026-11-06T10:00:00+00:00");
  assert.equal(split.recent.length, 1);
  assert.equal(split.earlier.length, 1);
  assert.equal(recentErrorCount({ state: "ok", lastTestedAt: "2026-11-06T13:00:00+00:00", recentErrors: errors }), 0,
    "working and nothing newer: no count");
  assert.equal(recentErrorCount({ state: "ok", lastTestedAt: null, recentErrors: errors }), 0, "working without a test time");
  assert.equal(recentErrorCount({ state: "failing", lastTestedAt: "2026-11-06T13:00:00+00:00", recentErrors: errors }), 2);
});

test("rendered Errors tab: sentences with the code as tooltip, older errors under Earlier", async () => {
  const detail = { ...DETAIL, recent_errors: [
    { at: "2026-11-06T12:00:00+00:00", use: "tickets", message: "jql_invalid" },
    { at: "2026-10-05T08:00:00+00:00", use: "knowledge", message: "scope_not_allowed" }] };
  const srv = server({ [`GET /api/v1/admin/connections/${ID}`]: () => reply(200, detail) });
  const { view } = await render(srv, `?area=admin&tab=adminConnections&connection=${ID}`);
  const tab = view.root.find((node) => node.props.role === "tab" && node.props.id === "connection-tab-tab-errors");
  await act(async () => { tab.props.onClick(); });
  const tabPanel = byId(view.root, "connection-tab-errors");
  assert.match(text(tabPanel), /Since the last successful test/);
  const sentences = allById(tabPanel, "connection-error-sentence");
  assert.equal(sentences[0].props.title, "jql_invalid");
  assert.equal(text(sentences[0]), "The ticket filter is not valid JQL.");
  assert.doesNotMatch(text(byId(tabPanel, "connection-errors")), /jql_invalid|scope_not_allowed/);
  assert.match(text(byId(tabPanel, "connection-errors-earlier")), /Earlier \(1\)/);
  act(() => view.unmount());
});

// Bitbucket signs in like Jira on Server/Data Center (user and password, HTTP access token, OpenID Connect client
// credentials); Cloud keeps the Atlassian account email and API token. The access fields as the server lists them
// (backend connections/catalog.py for the bitbucket descriptor).
import { accessFieldOptions, accessFieldText, accessLabel, withAccessValue } from "../../src/admin/components/connections/authFields.ts";

const BB_KINDS = ["basic", "bearer_pat", "oidc_client_credentials", "cloud_api_token"];
const bbField = (key, label, extra = {}) => ({ key, label, required: false, secret: false, kind: "text", options: [],
  placeholder: "", auth_kinds: BB_KINDS, ...extra });
const BITBUCKET_TYPE = { type: "bitbucket", label: "Bitbucket", auth_kinds: BB_KINDS, uses: ["knowledge", "agent_tools", "repositories"],
  scope_key: "repositories", testable: true, access_fields: [
    bbField("bitbucket_deployment", "Where Bitbucket runs",
      { kind: "select", options: ["datacenter", "cloud"] }),
    bbField("bitbucket_url", "Bitbucket URL", { kind: "url", required: true, placeholder: "https://bitbucket.example.com" }),
    bbField("bitbucket_auth_mode", "Authentication", { kind: "select", required: true, options: BB_KINDS }),
    bbField("bitbucket_username", "Username", { required: true, auth_kinds: ["basic", "cloud_api_token"] }),
    bbField("bitbucket_password", "Password", { required: true, secret: true, kind: "secret", auth_kinds: ["basic"] }),
    bbField("bitbucket_token", "HTTP access token", { required: true, secret: true, kind: "secret", auth_kinds: ["bearer_pat", "cloud_api_token"] }),
    bbField("bitbucket_oidc_token_url", "OpenID Connect token endpoint URL", { kind: "url", required: true, auth_kinds: ["oidc_client_credentials"] }),
    bbField("bitbucket_oidc_client_id", "Client id", { required: true, auth_kinds: ["oidc_client_credentials"] }),
    bbField("bitbucket_oidc_client_secret", "Client secret", { required: true, secret: true, kind: "secret", auth_kinds: ["oidc_client_credentials"] }),
    bbField("bitbucket_oidc_scope", "Scope (optional)", { auth_kinds: ["oidc_client_credentials"] }),
    bbField("bitbucket_oidc_audience", "Audience (optional)", { auth_kinds: ["oidc_client_credentials"] }),
    bbField("bitbucket_oidc_client_auth", "Client authentication (optional)", { kind: "select",
      options: ["client_secret_post", "client_secret_basic"], auth_kinds: ["oidc_client_credentials"] }),
  ] };

test("Bitbucket: Data Center shows the chosen mode's fields and its own labels; Cloud the email and API token", () => {
  const [bb] = readConnectionTypes([BITBUCKET_TYPE]);
  const shown = (values) => keys(visibleAccessFields("bitbucket", bb.accessFields, values));
  const dc = { bitbucket_deployment: "datacenter" };
  const always = ["bitbucket_deployment", "bitbucket_url", "bitbucket_auth_mode"];
  assert.deepEqual(shown({ ...dc, bitbucket_auth_mode: "basic" }), [...always, "bitbucket_username", "bitbucket_password"]);
  assert.deepEqual(shown({ ...dc, bitbucket_auth_mode: "bearer_pat" }), [...always, "bitbucket_token"]);
  assert.deepEqual(shown({ ...dc, bitbucket_auth_mode: "oidc_client_credentials" }), [...always, "bitbucket_oidc_token_url",
    "bitbucket_oidc_client_id", "bitbucket_oidc_client_secret", "bitbucket_oidc_scope", "bitbucket_oidc_audience",
    "bitbucket_oidc_client_auth"]);
  // without a chosen mode no credential field shows: the mode is chosen explicitly first
  assert.deepEqual(shown(dc), always);
  // Cloud: no mode choice, the email and the API token, whatever mode is stored
  for (const mode of ["", "cloud_api_token", "oidc_client_credentials"]) {
    assert.deepEqual(shown({ bitbucket_deployment: "cloud", bitbucket_auth_mode: mode }),
      ["bitbucket_deployment", "bitbucket_url", "bitbucket_username", "bitbucket_token"], mode);
  }
  const label = (key, values) => accessFieldText("bitbucket", bb.accessFields.find((field) => field.key === key), values).label;
  assert.equal(label("bitbucket_username", dc), "Username");
  assert.equal(label("bitbucket_token", dc), "HTTP access token");
  assert.equal(label("bitbucket_username", { bitbucket_deployment: "cloud" }), "Atlassian account email");
  assert.equal(label("bitbucket_token", { bitbucket_deployment: "cloud" }), "Atlassian API token (with Bitbucket scopes)");
  // the named-connection form (NamedFieldsForm) takes the same Cloud labels by key
  assert.equal(accessLabel("bitbucket", "bitbucket_username", { bitbucket_deployment: "cloud" }, "Username"), "Atlassian account email");
  assert.equal(accessLabel("bitbucket", "bitbucket_username", dc, "Username"), "Username");
  const mode = bb.accessFields.find((field) => field.key === "bitbucket_auth_mode");
  assert.deepEqual(accessFieldOptions("bitbucket", mode, dc, BB_KINDS), ["basic", "bearer_pat", "oidc_client_credentials"],
    "Data Center offers no Cloud sign-in");
  assert.deepEqual(accessFieldOptions("jira", mode, {}, BB_KINDS), BB_KINDS, "other types unchanged");
  // moving to Cloud clears a Server mode (the server refuses it there); moving back drops the Cloud mode
  assert.equal(withAccessValue("bitbucket", { ...dc, bitbucket_auth_mode: "bearer_pat" }, "bitbucket_deployment", "cloud").bitbucket_auth_mode, "");
  assert.equal(withAccessValue("bitbucket", { bitbucket_deployment: "cloud", bitbucket_auth_mode: "cloud_api_token" },
    "bitbucket_deployment", "datacenter").bitbucket_auth_mode, "");
  assert.equal(withAccessValue("bitbucket", { ...dc, bitbucket_auth_mode: "basic" }, "bitbucket_url", "x").bitbucket_auth_mode, "basic");
});

test("rendered Add connection: Bitbucket is proposed as the name; Data Center labels and modes, Cloud texts only on Cloud", async () => {
  const srv = server({ "GET /api/v1/admin/connection-types": () => reply(200, [...TYPES, BITBUCKET_TYPE]),
    "POST /api/v1/admin/connections": () => reply(201, { ...DETAIL, id: "new-bb", type: "bitbucket", name: "Bitbucket" }) });
  const { view } = await render(srv);
  await act(async () => { byId(view.root, "connections-add").props.onClick(); });
  const choose = async (testId, value) => {
    await act(async () => { byId(view.root, testId).props.onChange({ target: { value } }); });
  };
  await choose("connection-add-type", "jira");
  assert.equal(byId(view.root, "connection-add-name").props.value, "Jira");
  await choose("connection-add-name", "Team repos");
  await choose("connection-add-type", "github");
  assert.equal(byId(view.root, "connection-add-name").props.value, "Team repos", "a typed name is kept");
  await choose("connection-add-name", "");
  await choose("connection-add-type", "bitbucket");
  assert.equal(byId(view.root, "connection-add-name").props.value, "Bitbucket", "the proposal follows the type");
  const panel = () => byId(view.root, "connection-add-panel");
  const fieldText = (key) => text(view.root.find((node) => node.props["data-field"] === `access.${key}`));
  assert.equal(byId(view.root, "connection-access-bitbucket_deployment").props.value, "datacenter");
  assert.deepEqual(byId(view.root, "connection-access-bitbucket_deployment").findAll((node) => node.type === "option").map(text),
    ["Server / Data Center", "Bitbucket Cloud"]);
  assert.equal(byId(view.root, "connection-access-bitbucket_auth_mode").props.value, "basic");
  assert.deepEqual(byId(view.root, "connection-access-bitbucket_auth_mode").findAll((node) => node.type === "option").map(text),
    ["User and password", "Personal access token", "OpenID Connect client credentials"]);
  assert.match(fieldText("bitbucket_username"), /^Username \(required\)/);
  assert.doesNotMatch(text(panel()), /Atlassian|Bitbucket Cloud: the Atlassian account email|API token/,
    "no Cloud texts on Data Center");

  await choose("connection-access-bitbucket_auth_mode", "oidc_client_credentials");
  assert.equal(allById(view.root, "connection-access-bitbucket_username").length, 0);
  assert.ok(byId(view.root, "connection-access-bitbucket_oidc_token_url"));
  assert.equal(byId(view.root, "connection-secret-bitbucket_oidc_client_secret").props.type, "password");
  assert.match(text(byId(view.root, "connection-add-hint")),
    /Fill in Bitbucket URL, OpenID Connect token endpoint URL, Client id, Client secret\./);
  assert.deepEqual(byId(view.root, "connection-access-bitbucket_oidc_client_auth").findAll((node) => node.type === "option").map(text),
    ["Choose…", "Client secret in the request body", "HTTP Basic authentication"], "no raw client_secret_post");

  await choose("connection-access-bitbucket_deployment", "cloud");
  assert.equal(allById(view.root, "connection-access-bitbucket_auth_mode").length, 0, "Cloud has no mode choice");
  assert.match(fieldText("bitbucket_username"), /^Atlassian account email \(required\)/);
  assert.match(fieldText("bitbucket_token"), /^Atlassian API token \(with Bitbucket scopes\) \(required\)/);
  assert.equal(allById(view.root, "connection-secret-bitbucket_password").length, 0);
  assert.equal(byId(view.root, "connection-access-bitbucket_url").props.placeholder, "https://bitbucket.org");
  await choose("connection-access-bitbucket_url", "https://bitbucket.org");
  await choose("connection-access-bitbucket_username", "me@example.com");
  await act(async () => { byId(view.root, "connection-secret-bitbucket_token").props.onChange({ target: { value: "tok" } }); });
  await act(async () => { byId(view.root, "connection-add-submit").props.onClick(); });
  await act(async () => {});
  const post = srv.calls.find((call) => call.method === "POST" && call.url === "/api/v1/admin/connections");
  assert.deepEqual(post.body.access, { bitbucket_deployment: "cloud", bitbucket_url: "https://bitbucket.org",
    bitbucket_username: "me@example.com", bitbucket_token: "tok" }, "Cloud is saved without a mode");
  assert.equal(post.body.name, "Bitbucket");
  act(() => view.unmount());
});
