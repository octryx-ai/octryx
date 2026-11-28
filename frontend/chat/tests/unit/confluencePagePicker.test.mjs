// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/confluencePagePicker.test.mjs
//
// Connector UX (delivery 5): "Choose pages" on the Confluence card. Per allowed space either the whole space
// or chosen pages; per page "page and all below", "this page only" or excluded (exclusions inside an included
// branch allowed). The choices compile to confluence_allowed_pages entries in the backend's shape
// (services/confluence_pages/rules.py; the tree and rules are those of backend tests/services/connectors/test_confluence_page_rules.py).
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
  choose,
  compileRules,
  effective,
  nothingChosen,
  pagesSummary,
  pickerState,
  setMode,
  withLevel,
} from "../../src/admin/components/connectorsTab/confluencePagePickerModel.ts";
import { connectionTested } from "../../src/admin/components/connectorsTab/confluenceScopeModel.ts";
import { pickerSpaces } from "../../src/admin/components/connectorsTab/confluencePickerSpaces.ts";
import { buildLimits, draftFromAccess } from "../../src/admin/components/projectsTab/ProjectConnectorSettingsHelpers.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

// 10 Page1 ─┬ 20 Page2 ── 21 Page2.1
//           └ 30 Page3 ─┬ 31 Page3.1
//                       └ 32 Page3.2 ── 33 Page3.2.1
function loaded(choices = {}) {
  let state = pickerState("", ["SPACE1"]);
  state = setMode(state, "SPACE1", "pages");
  state = withLevel(state, "SPACE1", null, [{ id: "10", title: "Page1" }]);
  state = withLevel(state, "SPACE1", "10", [{ id: "20", title: "Page2" }, { id: "30", title: "Page3" }]);
  state = withLevel(state, "SPACE1", "20", [{ id: "21", title: "Page2.1" }]);
  state = withLevel(state, "SPACE1", "30", [{ id: "31", title: "Page3.1" }, { id: "32", title: "Page3.2" }]);
  state = withLevel(state, "SPACE1", "32", [{ id: "33", title: "Page3.2.1" }]);
  for (const [id, choice] of Object.entries(choices)) state = choose(state, id, choice);
  return state;
}

const BACKEND_RULES = [
  { id: "10", title: "Page1", space_key: "SPACE1", enabled: true, include_children: true, excludes: ["30"] },
  { id: "32", title: "Page3.2", space_key: "SPACE1", enabled: true, include_children: true },
];

test("subtree with an excluded branch and a branch included again compiles to the backend's entries", () => {
  const state = loaded({ 10: "subtree", 30: "excluded", 32: "subtree" });
  assert.deepEqual(compileRules(state), BACKEND_RULES);
  const readable = ["10", "20", "21", "30", "31", "32", "33"].filter((id) => effective(state, id).included);
  assert.deepEqual(readable, ["10", "20", "21", "32", "33"]);
  assert.deepEqual(effective(state, "31"), { included: false, inherited: true });
  assert.deepEqual(effective(state, "21"), { included: true, inherited: true });
});

test("'this page only' inside an included branch keeps the page and cuts what is below it", () => {
  const state = loaded({ 10: "subtree", 30: "page" });
  assert.deepEqual(compileRules(state), [
    { id: "10", title: "Page1", space_key: "SPACE1", enabled: true, include_children: true, excludes: ["30"] },
    { id: "30", title: "Page3", space_key: "SPACE1", enabled: true, include_children: false },
  ]);
  assert.equal(effective(state, "30").included, true);
  assert.equal(effective(state, "31").included, false, "below a page-only choice");
});

test("a whole space with an excluded branch; stored entries round-trip without loading the tree", () => {
  let state = setMode(loaded({ 30: "excluded" }), "SPACE1", "whole");
  const rules = compileRules(state);
  assert.deepEqual(rules, [{ space_key: "SPACE1", whole_space: true, enabled: true, excludes: ["30"] }]);
  assert.equal(effective(state, "21").included, true);
  assert.equal(effective(state, "31").included, false);

  for (const stored of [rules, BACKEND_RULES]) {
    state = pickerState(JSON.stringify(stored), ["SPACE1"]);
    assert.deepEqual(compileRules(state), stored, "an unchanged picker writes back what was stored");
  }
  // A stored page-only entry inside an excluded branch keeps the exclude, whatever the entry order.
  const order = [BACKEND_RULES[1], { id: "30", space_key: "SPACE1", enabled: true }, BACKEND_RULES[0]];
  const again = compileRules(pickerState(JSON.stringify(order), ["SPACE1"]));
  assert.deepEqual(again.find((entry) => entry.id === "10").excludes, ["30"]);
});

test("entries the picker does not edit are kept: other spaces, a legacy exclusion whose place is not loaded", () => {
  const stored = [
    { id: "900", space_key: "OTHER", enabled: true, include_children: true },
    { id: "5", title: "Legacy", enabled: true },
    { id: "10", space_key: "SPACE1", enabled: true, include_children: true },
    { id: "30", title: "Draft", space_key: "SPACE1", enabled: false },
  ];
  const rules = compileRules(pickerState(JSON.stringify(stored), ["SPACE1"]));
  assert.deepEqual(rules.slice(0, 2), stored.slice(0, 2));
  assert.deepEqual(rules.find((entry) => entry.id === "30"), { id: "30", title: "Draft", space_key: "SPACE1", enabled: false });
  assert.equal(pickerState("{}", ["SPACE1"]), null, "a non-list is left to Advanced");
});

test("nothing stored means whole spaces; narrowing every space without a choice is pointed out", () => {
  const state = pickerState("", ["SPACE1", "SPACE2"]);
  assert.deepEqual(state.modes, { SPACE1: "whole", SPACE2: "whole" });
  assert.deepEqual(compileRules(state), [], "no page rules: the spaces decide");
  const narrowedOne = setMode(state, "SPACE2", "pages");
  assert.deepEqual(compileRules(narrowedOne), [{ space_key: "SPACE1", whole_space: true, enabled: true }],
    "SPACE2 then reads only chosen pages (none)");
  assert.equal(nothingChosen(narrowedOne), false);
  assert.equal(nothingChosen(setMode(narrowedOne, "SPACE1", "pages")), true);
});

test("the card summarises the page list in words", () => {
  assert.match(pagesSummary(""), /No page restriction/);
  assert.equal(pagesSummary(JSON.stringify(BACKEND_RULES)),
    "Only chosen pages: 2 pages with everything below, 1 excluded branch. Pages of other spaces are not readable unless chosen.");
  assert.match(pagesSummary("[oops"), /cannot be read/);
});

test("'Choose pages' opens only after a successful test of the saved connection", () => {
  const connector = { tool_name: "confluence", configured: true, health: { status: "ok" } };
  assert.equal(connectionTested(connector, {}), true);
  assert.equal(connectionTested(connector, { confluence: { ok: false } }), false, "this session's failed test wins");
  assert.equal(connectionTested({ ...connector, health: { status: "error" } }, { confluence: { ok: true } }), true);
  assert.equal(connectionTested({ ...connector, configured: false }, { confluence: { ok: true } }), false);
});

test("Workspace limits keep subtrees, excludes and whole spaces through the one-line-per-page text", () => {
  const stored = [...BACKEND_RULES, { space_key: "SPACE2", whole_space: true, enabled: true }];
  const access = { connector_name: "confluence", limit_fields: ["confluence_allowed_pages"], project_enabled: true,
    project_limits: { confluence_allowed_pages: stored } };
  const draft = draftFromAccess(access);
  assert.equal(draft.confluencePages, "10 | Page1 | SPACE1\n32 | Page3.2 | SPACE1");
  assert.deepEqual(buildLimits(draft, ["confluence_allowed_pages"]).confluence_allowed_pages, stored);
  const edited = { ...draft, confluencePages: "32 | Page3.2 | SPACE1\n77" };
  assert.deepEqual(buildLimits(edited, ["confluence_allowed_pages"]).confluence_allowed_pages, [
    BACKEND_RULES[1],
    { id: "77", title: "", space_key: "", enabled: true, include_children: false },
    stored[2],
  ]);
});

function load(relative) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, JSON, encodeURIComponent,
      window: { addEventListener: () => {}, removeEventListener: () => {} },
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

const LEVELS = {
  "": [{ id: "10", title: "Page1" }],
  10: [{ id: "20", title: "Page2" }, { id: "30", title: "Page3" }],
  30: [{ id: "31", title: "Page3.1" }, { id: "32", title: "Page3.2" }],
};

const named = (name, bound, extra = {}) => ({ id: `id-${name}`, name, scope: "global", bound_scopes: bound,
  fields: {}, secret_status: {}, last_test: { ok: true, at: null, summary: "" }, ...extra });
const NAMED_LIST = { descriptor: { connector_name: "confluence", label: "Confluence", fields: [], form: "atlassian_auth",
  binding: { label: "Space", plural: "Spaces", pattern: "~?[A-Za-z0-9_]{1,64}", case: "upper", example: "" } },
  default: { configured: true, active: true, fields: {} }, connections: [named("client-b", ["SPACE2"])] };

async function mountCard({ ready = true, pages = "", list = null } = {}) {
  const { ConfluenceScopeFields } = load("admin/components/connectorsTab/ConfluenceScopeFields.tsx");
  const draft = { confluence_allowed_spaces: '[{"space_key": "SPACE1", "enabled": true}]', confluence_allowed_pages: pages };
  const urls = [];
  const readJson = async (url) => {
    if (url.includes("/named-connections")) {
      if (!list) throw new Error("no named connections");
      return list;
    }
    urls.push(url);
    const parent = new URL(url, "http://x").searchParams.get("parent_id") ?? "";
    return { space_key: "SPACE1", parent_id: parent || null, pages: LEVELS[parent] ?? [], start: 0, next_start: null };
  };
  let view;
  const render = () => createElement(ConfluenceScopeFields, {
    toolName: "confluence", draft: { ...draft }, browse: { readJson, ready },
    set: (field, value) => { draft[field] = value; view.update(render()); },
  });
  await act(async () => { view = TestRenderer.create(render()); });
  const button = (label) => view.root.find((node) => node.type === "button" && (text(node).trim() === label || node.props["aria-label"] === label));
  return {
    draft, urls, view,
    click: async (label) => { await act(async () => { button(label).props.onClick(); }); },
    disabled: (label) => button(label).props.disabled,
    radio: async (value, space = null) => {
      await act(async () => { view.root.find((node) => node.type === "input" && node.props.value === value
        && (!space || node.props.name === `page-picker-mode-${space}`)).props.onChange(); });
    },
    choose: async (title, value) => {
      await act(async () => { view.root.find((node) => node.type === "select" && node.props["aria-label"] === `Choice for ${title}`).props.onChange({ target: { value } }); });
    },
    state: (id) => text(view.root.find((node) => node.props["data-testid"] === `page-state-${id}`)),
    all: () => text(view.root),
  };
}

test("rendered: open a space and its pages lazily, choose per page, apply into the draft", async () => {
  const ui = await mountCard();
  await ui.click("Choose pages");
  await ui.radio("pages");
  await ui.click("Open space SPACE1");
  assert.deepEqual(ui.urls, ["/admin/chat/api/panel/connectors/confluence/page-tree?space_key=SPACE1&start=0"]);
  await ui.click("Open Page1");
  await ui.choose("Page1", "subtree");
  await ui.click("Open Page3");
  assert.match(ui.urls[2], /parent_id=30/);
  await ui.click("Close Page3");
  await ui.click("Open Page3");
  assert.equal(ui.urls.length, 3, "each level is read once, when first opened");
  await ui.choose("Page3", "excluded");
  await ui.choose("Page3.2", "subtree");
  assert.equal(ui.state("20"), "Readable · inherited");
  assert.equal(ui.state("31"), "Not readable · inherited");
  await ui.click("Apply");
  assert.deepEqual(JSON.parse(ui.draft.confluence_allowed_pages), BACKEND_RULES);
  assert.match(ui.all(), /2 pages with everything below, 1 excluded branch/);
  assert.equal(ui.view.root.findAll((node) => node.props["data-testid"] === "confluence-page-picker").length, 0);
});

test("rendered: without a successful test the picker stays closed; a failed level read is shown in words", async () => {
  const closed = await mountCard({ ready: false });
  assert.equal(closed.disabled("Choose pages"), true);
  assert.match(closed.all(), /Test the saved connection first\./);

  const ui = await mountCard();
  const failing = async () => { throw Object.assign(new Error("Conflict"), { code: "connection_not_configured_for_scope" }); };
  const { ConfluencePagePicker } = load("admin/components/connectorsTab/ConfluencePagePicker.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(ConfluencePagePicker, {
      spaces: ["SPACE9"], draftValue: "", readJson: failing, onApply: () => {}, onClose: () => {},
    }));
  });
  await act(async () => { view.root.find((node) => node.props["aria-label"] === "Open space SPACE9").props.onClick(); });
  assert.match(text(view.root), /No saved connection serves this space/);
  assert.ok(ui);
});

test("rendered: nothing chosen is never applied silently; whole spaces or cancel is an explicit choice", async () => {
  const ui = await mountCard({ pages: "" });
  await ui.click("Choose pages");
  await ui.radio("pages");
  await ui.click("Apply");
  assert.equal(ui.draft.confluence_allowed_pages, "", "nothing written yet");
  assert.match(ui.all(), /No page is chosen\. Without a page restriction every page of the allowed spaces is readable/);
  assert.equal(ui.disabled("Apply"), true, "the question is answered first");
  await ui.click("Cancel, choose pages");
  assert.equal(ui.draft.confluence_allowed_pages, "");
  assert.equal(ui.view.root.findAll((node) => node.props.role === "alertdialog").length, 0);
  assert.equal(ui.view.root.findAll((node) => node.props["data-testid"] === "confluence-page-picker").length, 1,
    "the picker stays open to choose pages");
  await ui.click("Apply");
  await ui.click("Make the whole spaces readable");
  assert.deepEqual(JSON.parse(ui.draft.confluence_allowed_pages), []);
  assert.equal(ui.view.root.findAll((node) => node.props["data-testid"] === "confluence-page-picker").length, 0);
});

test("the picker's spaces: the allowed ones, then every named connection's (Workspace: own, then inherited)", () => {
  const list = { connections: [{ name: "client-b", boundScopes: ["SPACE2"], lastTest: { ok: false } },
    { name: "client-c", boundScopes: ["SPACE3", "space1"], lastTest: null }],
  inherited: [{ name: "global-d", servedHere: ["SPACE4"], boundScopes: ["SPACE4", "SPACE2"], lastTest: { ok: true } }] };
  assert.deepEqual(pickerSpaces(["SPACE1"], list), {
    spaces: ["SPACE1", "SPACE2", "SPACE3", "SPACE4"],
    servedBy: { SPACE1: "client-c", SPACE2: "client-b", SPACE3: "client-c", SPACE4: "global-d" },
    namedTested: true,
  });
  assert.deepEqual(pickerSpaces(["SPACE1"], null), { spaces: ["SPACE1"], servedBy: {}, namedTested: false });
});

test("rendered: the second connection's space is in the picker and is read through the tree", async () => {
  const ui = await mountCard({ ready: false, list: NAMED_LIST });
  assert.equal(ui.disabled("Choose pages"), false, "a tested named connection opens the picker");
  await ui.click("Choose pages");
  assert.match(ui.all(), /SPACE2via client-b/);
  await ui.radio("pages", "SPACE2");
  await ui.click("Open space SPACE2");
  assert.deepEqual(ui.urls, ["/admin/chat/api/panel/connectors/confluence/page-tree?space_key=SPACE2&start=0"]);
  await ui.choose("Page1", "subtree");
  await ui.click("Apply");
  assert.deepEqual(JSON.parse(ui.draft.confluence_allowed_pages), [
    { id: "10", title: "Page1", space_key: "SPACE2", enabled: true, include_children: true },
    { space_key: "SPACE1", whole_space: true, enabled: true },
  ], "the default's space stays whole while the second connection's space is narrowed");
});

test("rendered: a Workspace chooses pages of its named connections through its own tree endpoint", async () => {
  const { WorkspaceConfluencePages } = load("admin/components/projectsTab/WorkspaceConfluencePages.tsx");
  const list = { ...NAMED_LIST, connections: [named("ws-a", ["WS1"], { scope: "workspace" })],
    inherited: [named("client-b", ["SPACE2"], { served_here: ["SPACE2"] })] };
  const urls = [];
  const readJson = async (url) => {
    if (url.includes("/named-connections")) return list;
    urls.push(url);
    const parent = new URL(url, "http://x").searchParams.get("parent_id") ?? "";
    return { pages: LEVELS[parent] ?? [], next_start: null };
  };
  let draft = { ...draftFromAccess({ connector_name: "confluence", limit_fields: ["confluence_allowed_pages"],
    project_enabled: true, project_limits: {}, inherited_limits: { confluence_allowed_spaces: [{ space_key: "SPACE1" }] } }) };
  const access = { connector_name: "confluence", inherited_limits: { confluence_allowed_spaces: [{ space_key: "SPACE1" }] } };
  let view;
  const render = () => createElement(WorkspaceConfluencePages, {
    projectId: "p 1", access, draft, readJson, update: (patch) => { draft = { ...draft, ...patch }; view.update(render()); },
  });
  await act(async () => { view = TestRenderer.create(render()); });
  const click = async (label) => {
    await act(async () => { view.root.find((node) => node.type === "button" && (text(node).trim() === label || node.props["aria-label"] === label)).props.onClick(); });
  };
  await click("Choose pages");
  const shown = view.root.findAll((node) => node.props["data-space"]).map((node) => node.props["data-space"]);
  assert.deepEqual(shown, ["SPACE1", "WS1", "SPACE2"]);
  await act(async () => { view.root.find((node) => node.type === "input" && node.props.name === "page-picker-mode-WS1" && node.props.value === "pages").props.onChange(); });
  await click("Open space WS1");
  assert.deepEqual(urls, ["/admin/chat/api/panel/projects/p%201/connectors/confluence/page-tree?space_key=WS1&start=0"]);
  await act(async () => { view.root.find((node) => node.type === "select" && node.props["aria-label"] === "Choice for Page1").props.onChange({ target: { value: "subtree" } }); });
  await click("Apply");
  const limits = buildLimits(draft, ["confluence_allowed_pages"]);
  assert.deepEqual(limits.confluence_allowed_pages, [
    { id: "10", title: "Page1", space_key: "WS1", enabled: true, include_children: true },
    { space_key: "SPACE1", whole_space: true, enabled: true },
    { space_key: "SPACE2", whole_space: true, enabled: true },
  ]);
});
