// Render guards for admin parts split into smaller functions: the evidence grounding card, the models overview, the
// REST definition fields, the turn explainer, the REST add panel with its import result, and the setup guide card
// render the same structure and make the same calls.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, plain } from "./adminGuardRenderers.mjs";
import { jsonRoutes, loadStubbed, stubs } from "./adminGuardStubLoader.mjs";
import { button, hostCount } from "./adminGuardTreeReaders.mjs";

test("the evidence grounding card loads the list in words and saves or resets it", async () => {
  const requests = [];
  let answer = { ok: true, data: { high_risk_agent_types: ["document_updater"], high_risk_agent_types_source: "configured",
    default_high_risk_agent_types: ["document_updater", "code-reviewer"] } };
  const governed = { governedRequest: async (url, init) => { requests.push([url, init.method, init.body]); return answer; } };
  const { RuntimeEvidenceGroundingSection } = loadStubbed("admin/components/runtimeTab/RuntimeEvidenceGroundingSection.tsx",
    ["/GovernedIssueList"], {}, { "/governedRequest": governed });
  const view = await createAsync(createElement(RuntimeEvidenceGroundingSection));
  includesAll(text(view.root), ["Evidence grounding", "A saved list applies", " · default: Document updater, Code reviewer",
    "High-risk agent types (one per line)", "Save agent types", "Reset to the default list"]);
  assert.equal(all(view, "textarea")[0].props.value, "document_updater");
  assert.equal(hostCount(view), 12);
  act(() => all(view, "textarea")[0].props.onChange({ target: { value: "a\nb, a" } }));
  answer = { ok: true, data: { high_risk_agent_types: ["a", "b"], high_risk_agent_types_source: "configured" } };
  await act(async () => button(view, "Save agent types").props.onClick());
  await tick();
  assert.deepEqual(plain(requests[1].slice(1)), ["PUT", { high_risk_agent_types: ["a", "b"] }]);
  includesAll(text(view.root), ["High-risk agent types saved."]);
  answer = { ok: true, data: {} };
  await act(async () => button(view, "Reset to the default list").props.onClick());
  await tick();
  assert.deepEqual(plain(requests[2][2]), { high_risk_agent_types: null });
  includesAll(text(view.root), ["Reset to the default list.", "The default list applies"]);
  assert.equal(button(view, "Reset to the default list").props.disabled, true);
  answer = { ok: false, issues: [{ path: "x", message: "bad" }] };
  await act(async () => button(view, "Save agent types").props.onClick());
  await tick();
  assert.equal(plain(stubs(view, "GovernedIssueList")[0].props.issues).length, 1);
  const loading = create(createElement(loadStubbed("admin/components/runtimeTab/RuntimeEvidenceGroundingSection.tsx",
    ["/GovernedIssueList"], {}, { "/governedRequest": { governedRequest: () => new Promise(() => {}) } }).RuntimeEvidenceGroundingSection));
  includesAll(text(loading.root), ["Loading…"]);
  assert.equal(button(loading, "Save agent types").props.disabled, true);
});

const overview = {
  workspaces: 3, platform_default: "Haiku",
  providers: [
    { id: "p1", name: "Bedrock", driver: "bedrock", endpoint: "eu", state: "connected", error: null, models_found: 4, models_on: 2,
      loaded_at: "2026-01-01T00:00:00Z" },
    { id: "p2", name: "Local", driver: "ollama", endpoint: null, state: "off", error: "down", models_found: 0, models_on: 0, loaded_at: null },
  ],
  models: [
    { key: "m1", label: "Haiku", provider: "Bedrock", price_in: 1, price_out: 5, cost_source: null, available_in: 3, off_in: [],
      default_in: ["A"], platform_default: true },
    { key: "m2", label: "Qwen", provider: "Local", price_in: null, price_out: null, cost_source: null, available_in: 0, off_in: ["A", "B"],
      default_in: [], platform_default: false, provider_off: true },
  ],
};

test("the models overview lists providers and models and opens the owning pages", async () => {
  const opened = [];
  const load = (readJson) => loadStubbed("admin/components/modelsOverview/AdminModelsOverview.tsx", ["/StatusLabel", "/TimeText"], {},
    { "/adminPanelHelpers": { readJson }, "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) } });
  const { readJson, calls } = jsonRoutes({ "/api/v1/admin/model-catalog/overview": overview });
  const view = await createAsync(createElement(load(readJson).AdminModelsOverview));
  assert.equal(calls[0].url, "/api/v1/admin/model-catalog/overview");
  includesAll(text(view.root), ["Global · applies to all 3 workspaces.", "Providers", "Bedrock", "bedrock · eu", "4 models found · 2 switched on",
    " · loaded ", "ollama", "Its models are not offered", "down", "Platform default: Haiku", "$1.00 / $5.00", "All 3",
    "Default in “A”", "Price missing · ", "add", "Not offered: provider switched off", "Off in 2 workspaces", "Prices come from"]);
  assert.deepEqual(stubs(view, "StatusLabel").map((node) => node.props.label), ["Connected", "Switched off"]);
  assert.equal(byTestId(view, "overview-provider-p2").length, 1);
  assert.equal(all(view, "tr").length, 3);
  assert.equal(hostCount(view), 53);
  for (const label of ["Add or edit providers", "Change default", "add"]) act(() => button(view, label).props.onClick());
  assert.deepEqual(opened, ["providers", "modelOrder", "modelCatalog"]);
  const failed = await createAsync(createElement(load(async () => { throw new Error("Nope"); }).AdminModelsOverview));
  assert.equal(text(failed.root), "Nope");
  const pending = create(createElement(load(() => new Promise(() => {})).AdminModelsOverview));
  assert.equal(text(pending.root), "Loading models…");
});

const draft = (patch = {}) => ({ servers: "https://a.example.com\nhttps://b.example.com", scheme: "oauth2_client_credentials",
  headerName: "", queryName: "", tokenUrl: "https://t", scopes: "read", timeout: "30", csrf: true, csrfHeader: "", csrfFetchPath: "", ...patch });

test("the REST definition fields show servers, auth fields and the CSRF switch and change the draft", () => {
  const { RestDefinitionFields } = loadStubbed("admin/components/restApis/RestDefinitionFields.tsx", []);
  const changes = [];
  const render = (props) => create(createElement(RestDefinitionFields, { draft: draft(), onChange: (next) => changes.push(next), error: null, ...props }));
  const view = render({ error: { field: "servers", index: 1, text: "Refused" } });
  includesAll(text(view.root), ["Servers", "One base URL each", "Remove", "Refused", "Add a server", "Authentication", "Timeout (seconds)",
    "Token URL", "Scopes (optional)", "Token header", "Token fetch path (optional)"]);
  assert.equal(byTestId(view, "rest-def-server-error").length, 1);
  assert.equal(all(view, "input")[1].props["aria-invalid"], true);
  assert.equal(hostCount(view), 46);
  act(() => byTestId(view, "rest-def-server-add")[0].props.onClick());
  act(() => button(view, "Remove").props.onClick());
  act(() => all(view, "input")[0].props.onChange({ target: { value: "https://c" } }));
  act(() => byTestId(view, "rest-def-csrf")[0].props.onChange({ target: { checked: false } }));
  act(() => byTestId(view, "rest-add-scheme")[0].props.onChange({ target: { value: "api_key_header" } }));
  assert.deepEqual(plain(changes.slice(0, 3).map((next) => next.servers)),
    ["https://a.example.com\nhttps://b.example.com\n", "https://b.example.com", "https://c\nhttps://b.example.com"]);
  assert.equal(changes[3].csrf, false);
  assert.equal(changes[4].scheme, "api_key_header");
  const header = render({ draft: draft({ scheme: "api_key_header", servers: "x", csrf: false }), context: { hasWrites: false, odata: false },
    error: { field: "servers", text: "All bad" } });
  includesAll(text(header.root), ["Header name", "Defaults to X-API-Key.", "All bad"]);
  assert.equal(all(header, "button").length, 1);
  assert.equal(byTestId(header, "rest-def-csrf").length, 0);
  const query = render({ draft: draft({ scheme: "api_key_query", csrf: false }) });
  includesAll(text(query.root), ["Query parameter name", "Defaults to api_key."]);
  assert.equal(byTestId(query, "rest-def-csrf").length, 1);
});

const explainOptions = { workspaces: [{ id: "w1", name: "Harbor", data_class: "internal" }, { id: "w2", name: "Dock", data_class: "" }],
  models: [{ key: "m1", name: "Haiku" }] };
const explained = { state: "fallback", title: "Haiku via fallback", note: "first failed",
  trace: [{ icon: "ok", label: "Pin", text: "none" }, { icon: "no", label: "Choice", text: "off" }] };

test("the turn explainer loads the Workspaces, explains each turn and shows the trace", async () => {
  const { readJson, calls } = jsonRoutes({ "/api/v1/admin/model-selection/explain/options": explainOptions,
    "/api/v1/admin/model-selection/explain": explained });
  const { ExplainTurn } = loadStubbed("admin/components/modelSelection/ExplainTurn.tsx", ["/LoadingState"], {},
    { "/adminPanelHelpers": { readJson } });
  const view = await createAsync(createElement(ExplainTurn));
  await act(async () => { await tick(); });
  includesAll(text(view.root), ["A turn", "Workspace", "Harbor (Internal)", "Dock (no data class)", "Person chose", "Nothing (Automatic)",
    "Agent pins", "No pin", "The first model times out", "Result", "Haiku via fallback", "first failed", "✓", "Pin", "✕", "Choice"]);
  assert.equal(byTestId(view, "explain-result")[0].props.className, "model-explain__result model-explain__result--bad");
  assert.equal(hostCount(view), 35);
  await act(async () => { all(view, "input")[0].props.onChange({ target: { checked: true } }); await tick(); });
  assert.deepEqual(plain(calls.filter((call) => call.method === "POST").map((call) => call.body)), [
    { workspace_id: "w1", person_choice: "", agent_pin: "", first_fails: false },
    { workspace_id: "w1", person_choice: "", agent_pin: "", first_fails: true }]);
  const pending = create(createElement(loadStubbed("admin/components/modelSelection/ExplainTurn.tsx", ["/LoadingState"], {},
    { "/adminPanelHelpers": { readJson: () => new Promise(() => {}) } }).ExplainTurn));
  assert.equal(stubs(pending, "LoadingState").length, 1);
});

test("the REST add panel imports or adds by hand, and the import result sets the default template", async () => {
  const calls = [];
  const imported = { id: "d1", name: "Shop", default_preset: "odata_v2", auth: { scheme: "basic", csrf: { fetch: true } }, warnings: ["w1"],
    operations: [{ id: "o1", method: "GET", path: "/Orders", preset: "odata_v2" }, { id: "o2", method: "POST", path: "/$batch" }] };
  const api = { importDefinition: async (body) => { calls.push(["import", body]); return imported; },
    createDefinition: async (body) => { calls.push(["create", body]); return { id: "d2" }; },
    updateDefinition: async (id, body) => { calls.push(["update", id, body]); return { ...imported, default_preset: "" }; },
    updateOperation: async () => null };
  const { RestApiAddPanel } = loadStubbed("admin/components/restApis/RestApiAddPanel.tsx", ["/SidePanel", "/StatusLabel", "./RestDefinitionFields"],
    {}, { "./restApisApi": api });
  const opened = [];
  const view = create(createElement(RestApiAddPanel, { onClose() {}, onOpen: (id) => opened.push(id) }));
  includesAll(text(view.root), ["Key", "Name (optional)", "Source", "Paste the document", "OpenAPI 3 or Swagger 2 document", "Cancel", "Import"]);
  assert.equal(hostCount(view), 23);
  act(() => byTestId(view, "rest-add-source")[0].props.onChange({ target: { value: "url" } }));
  includesAll(text(view.root), ["Document URL", "Fetched once through the public web egress."]);
  act(() => byTestId(view, "rest-add-key")[0].props.onChange({ target: { value: "shop" } }));
  act(() => stubs(view, "SidePanel")[0].props.tabs.onChange("manual"));
  includesAll(text(view.root), ["Name", "The secrets themselves belong to a connection", "Add REST API"]);
  assert.equal(stubs(view, "RestDefinitionFields").length, 1);
  assert.equal(byTestId(view, "rest-add-key")[0].props.value, "");
  act(() => byTestId(view, "rest-add-key")[0].props.onChange({ target: { value: "hand" } }));
  await act(async () => byTestId(view, "rest-add-submit")[0].props.onClick());
  assert.equal(calls[0][0], "create");
  assert.deepEqual(opened, ["d2"]);
  act(() => stubs(view, "SidePanel")[0].props.tabs.onChange("import"));
  await act(async () => byTestId(view, "rest-add-submit")[0].props.onClick());
  assert.equal(calls[1][0], "import");
  includesAll(text(view.root), ["Default template", "Detected in the document.", "on, as SAP Gateway needs for writes", "GET", "/Orders"]);
  assert.deepEqual(stubs(view, "StatusLabel").map((node) => node.props.label).length, 2);
  assert.equal(hostCount(view), 26);
  await act(async () => byTestId(view, "rest-import-template-select")[0].props.onChange({ target: { value: "" } }));
  assert.deepEqual(plain(calls[2]), ["update", "d1", { default_preset: "" }]);
  assert.equal(byTestId(view, "rest-import-template").length, 1);
  act(() => byTestId(view, "rest-import-open")[0].props.onClick());
  assert.deepEqual(opened, ["d2", "d1"]);
});

test("the setup guide card shows stats and steps and asks once before starting the local model", () => {
  const { ProvidersSetupGuideCard } = loadStubbed("admin/components/providerTab/ProvidersSetupGuideCard.tsx", []);
  const actions = [];
  const setupGuide = { ready: false, summary: "", stats: { active_provider_count: 2, api_provider_count: 1, local_provider_count: 1,
    active_runtime_count: 0 }, steps: [
    { key: "a", title: "Provider", status: "completed", description: "d", detail: "ok", blocking: true, action: "add", action_label: "Add" },
    { key: "b", title: "Local model", status: "open", description: "d", detail: "", blocking: true, action: "configure_local_anchor",
      action_label: "Set up" },
    { key: "c", title: "Keys", status: "open", description: "d", detail: "x", blocking: false, action: "keys", action_label: "Rotate" },
    { key: "d", title: "Info", status: "open", description: "d", detail: "", blocking: false, action: "", action_label: "" }] };
  const view = create(createElement(ProvidersSetupGuideCard, { ctx: { setupGuide, handleSetupGuideAction: (name) => actions.push(name) } }));
  includesAll(text(view.root), ["Platform setup guide", "Needs action", "2 active", "1 API", "0 runtimes",
    "Ready", "Required", "Recommended", "Set up", "Rotate"]);
  assert.deepEqual(buttons(view), ["Set up", "Rotate"]);
  assert.equal(all(view, "details")[0].props.open, true);
  assert.equal(hostCount(view), 35);
  act(() => button(view, "Set up").props.onClick());
  assert.deepEqual(actions, []);
  act(() => button(view, "Confirm: start it now").props.onClick());
  act(() => button(view, "Rotate").props.onClick());
  assert.deepEqual(actions, ["configure_local_anchor", "keys"]);
  assert.equal(create(createElement(ProvidersSetupGuideCard, { ctx: { setupGuide: null } })).toJSON(), null);
});
