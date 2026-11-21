// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/serviceNowRecordLimit.test.mjs
//
// Follow-ups 2 (frontend): the ServiceNow connector's services next to its assignment groups and how they combine
// (`servicenow_filter_mode`: all = group AND service, any = either, never outside both lists); the intake's narrowing
// services override with the effective groups and services; known values from recent records as suggestions.
// Requests are stubs; fixtures use neutral `.test` names only, plus the live value shapes (a trailing space).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  GROUPS_FIELD,
  MODE_FIELD,
  SERVICES_FIELD,
  addGroup,
  limitSummary,
  readKnownValues,
  serviceNowGroupsSaveFields,
  suggestionsFor,
} from "../../src/admin/components/connectorsTab/serviceNowGroupsModel.ts";
import { buildConnectorSaveBody } from "../../src/admin/hooks/connectorSaveBody.ts";
import {
  intakeErrorText,
} from "../../src/chat/work/incident/incidentSettingsModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (root, id) => root.findAll((node) => node.props && node.props["data-testid"] === id);

const POLICY = { tool_instructions: "", extra_tools: [], disabled_tools: [] };
function servicenow(publicFields = {}) {
  return {
    tool_name: "servicenow", label: "ServiceNow", description: "ServiceNow tables",
    fields: ["servicenow_url", "servicenow_auth_mode", "servicenow_token", "servicenow_allowed_tables", GROUPS_FIELD, SERVICES_FIELD, MODE_FIELD],
    secret_fields: ["servicenow_token"], supports_test: true, builtin_tools: [], tools: [], tool_policy: POLICY,
    is_active: true, policy_active: true, configured: true,
    public_fields: { servicenow_url: "https://servicenow.test", servicenow_auth_mode: "bearer_token", servicenow_allowed_tables: ["incident"], ...publicFields },
    secret_status: { servicenow_token: true }, db_id: null, policy_id: null,
  };
}
const KNOWN = {
  table: "incident", scanned: 300,
  assignment_groups: [{ name: "PP Solutions and Support", count: 280 }, { name: "CTS - Cloud Tech Solutions", count: 20 }],
  services: [{ name: "Risk", count: 120 }, { name: "Checkout API", count: 90 }, { name: "Payment platform service - Risk", count: 90 }],
};

// ---- models ---------------------------------------------------------------------------------------

test("connector model: services save like groups, the mode only when changed, both stay out of the generic panel", () => {
  assert.deepEqual(addGroup([], "  Checkout   API ", "service"), { groups: ["Checkout API"], problem: null });
  assert.equal(addGroup(["Risk"], "risk", "service").problem, "This service is already in the list.");
  assert.match(addGroup([], "a,b", "service").problem, /^A service must not contain/);
  const none = servicenow();
  assert.deepEqual(serviceNowGroupsSaveFields(none, { [SERVICES_FIELD]: '["Risk"]' }), { [SERVICES_FIELD]: ["Risk"] });
  const stored = servicenow({ [SERVICES_FIELD]: ["Risk"], [MODE_FIELD]: "any" });
  assert.deepEqual(serviceNowGroupsSaveFields(stored, { [SERVICES_FIELD]: "[]" }), { [SERVICES_FIELD]: [] }, "an explicit clear");
  assert.deepEqual(serviceNowGroupsSaveFields(stored, { [MODE_FIELD]: "any" }), {}, "an unchanged mode is not sent");
  assert.deepEqual(serviceNowGroupsSaveFields(stored, { [MODE_FIELD]: "all" }), { [MODE_FIELD]: "all" });
  assert.deepEqual(serviceNowGroupsSaveFields(none, { [MODE_FIELD]: "or" }), {}, "only the two modes");
  const body = buildConnectorSaveBody(none, { [SERVICES_FIELD]: '["Risk"]', [MODE_FIELD]: "any" }, POLICY);
  assert.deepEqual([body[SERVICES_FIELD], body[MODE_FIELD]], [["Risk"], "any"]);
});

test("limit in words and known values: AND/OR named, suggestions skip listed entries whitespace- and case-insensitively", () => {
  assert.equal(limitSummary([], [], "all"), null);
  assert.equal(limitSummary(["PP"], ["Risk"], "all"), "Only the assignment groups PP and the services Risk.");
  assert.equal(limitSummary(["PP"], ["Risk"], "any"), "Only the assignment groups PP or the services Risk.");
  assert.equal(limitSummary([], ["Risk"], "any"), "Only the services Risk.");
  const known = readKnownValues(KNOWN);
  assert.equal(known.scanned, 300);
  assert.deepEqual(suggestionsFor(known.groups, ["pp  solutions and support "]).map((entry) => entry.name), ["CTS - Cloud Tech Solutions"]);
  assert.equal(readKnownValues({ detail: "Not Found" }), null);
});

// ---- rendered ---------------------------------------------------------------------------------------

function makeLoader(extra = {}, stubs = {}) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (name.startsWith(".")) {
      const base = path.resolve(dir, name);
      for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return load(base + ext);
    }
    return require(name);
  };
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, setInterval, clearInterval, setTimeout, requestAnimationFrame: (callback) => callback(),
      document: { getElementById: () => null },
      window: { location: { origin: "http://localhost", search: "" }, setTimeout: () => 0, confirm: () => true, addEventListener: () => {}, removeEventListener: () => {} },
      ...extra,
      require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(SRC, relative));
}

function server(answer) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const call = { url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    const { status, body } = answer(call);
    return { ok: status < 400, status, statusText: "", json: async () => body };
  };
  return { fetch, calls };
}
const tick = (ms = 0) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });
const click = (node) => act(async () => { await node.props.onClick(); });
const typeEntry = async (view, testId, value) => {
  await act(async () => { byTestId(view.root, `${testId}-input`)[0].props.onChange({ target: { value } }); });
  await act(async () => { byTestId(view.root, `${testId}-input`)[0].props.onKeyDown({ key: "Enter", preventDefault: () => {} }); });
};
const options = (root, testId) => byTestId(root, `${testId}-known`).flatMap((list) => list.findAllByType("option").map((option) => option.props.value));

test("rendered connector: services chips next to groups; the mode appears once both are set; suggestions from the admin route", async () => {
  const srv = server((call) => (call.url.endsWith("/limit-values") ? { status: 200, body: KNOWN } : { status: 404, body: {} }));
  const loadModule = makeLoader({ fetch: srv.fetch }, {});
  const { ServiceNowAssignmentGroupsField } = loadModule("admin/components/connectorsTab/ServiceNowAssignmentGroupsField.tsx");
  const connector = servicenow({ [GROUPS_FIELD]: ["PP Solutions and Support"] });
  let draft = {};
  let view;
  const render = () => createElement(ServiceNowAssignmentGroupsField, {
    connector, draft, id: (field) => `cf-${field}`,
    set: (field, value) => { draft = { ...draft, [field]: value }; act(() => view.update(render())); },
  });
  act(() => { view = TestRenderer.create(render()); });
  assert.equal(byTestId(view.root, "servicenow-filter-mode").length, 0, "one list: no mode to choose");
  await typeEntry(view, "servicenow-services", "Risk");
  assert.deepEqual(JSON.parse(draft[SERVICES_FIELD]), ["Risk"]);
  const modes = byTestId(view.root, "servicenow-filter-mode")[0].findAllByType("input");
  assert.deepEqual(modes.map((input) => [input.props.value, input.props.checked]), [["all", true], ["any", false]]);
  act(() => modes[1].props.onChange());
  assert.equal(draft[MODE_FIELD], "any");
  assert.deepEqual(buildConnectorSaveBody(connector, draft, POLICY)[MODE_FIELD], "any");
  await click(byTestId(view.root, "servicenow-known-values")[0]);
  await tick();
  assert.deepEqual(srv.calls.map((call) => call.url), ["/admin/chat/api/panel/connectors/servicenow/limit-values"]);
  assert.deepEqual(options(view.root, "servicenow-assignment-groups"), ["CTS - Cloud Tech Solutions"]);
  assert.deepEqual(options(view.root, "servicenow-services"), ["Checkout API", "Payment platform service - Risk"]);
  act(() => view.unmount());
});
