// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeConfluencePageTree.test.mjs
//
// Confluence page-tree scope (frontend). A Confluence connector syncs whole
// spaces or page trees. A pasted page address (Cloud …/spaces/KEY/pages/ID/…, Data Center …viewpage.action?pageId=ID)
// is read visibly: its page id and space key are shown and added only by "Add page tree", the pasted text is never
// rewritten, and an address without the space asks for it. Several trees can be added. Saves send
// `page_trees: [{space_key, root_page_id}]`; pausing keeps them; the server's 422 shape refusals and 409
// scope_not_allowed are shown next to the scope.
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
  pageTreeToAdd,
  pageTreesProblem,
  readPageAddress,
  storedPageTrees,
} from "../../src/admin/components/workspaceKnowledge/confluencePageTree.ts";
import { initialForm, validate } from "../../src/admin/components/workspaceKnowledge/connectorFormModel.ts";
import { scopeRefusalText } from "../../src/admin/components/workspaceKnowledge/connectorScopeText.ts";
import { configOf } from "../../src/admin/components/workspaceKnowledge/connectorConfig.ts";
import { connectorsApi } from "../../src/admin/components/workspaceKnowledge/connectorsApi.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const CLOUD = "https://your-site.atlassian.net/wiki/spaces/DEMO/pages/100002/Engineering+Handbook";
const DC = "https://wiki.acme.test/confluence/pages/viewpage.action?pageId=131075";

// ---- model --------------------------------------------------------------------------------------

test("a pasted page address yields its page id and, when the address shows it, its space key", () => {
  assert.deepEqual(readPageAddress(CLOUD), { kind: "page", spaceKey: "DEMO", rootPageId: "100002" });
  assert.deepEqual(readPageAddress("https://your-site.atlassian.net/wiki/spaces/~jdoe/pages/123"), { kind: "page", spaceKey: "~jdoe", rootPageId: "123" });
  assert.deepEqual(readPageAddress("https://your-site.atlassian.net/wiki/spaces/DEMO/pages/edit-v2/100002"), { kind: "page", spaceKey: "DEMO", rootPageId: "100002" });
  assert.deepEqual(readPageAddress("https://wiki.acme.test/spaces/ENG/pages/42/Title?focused=1#x"), { kind: "page", spaceKey: "ENG", rootPageId: "42" });
  assert.deepEqual(readPageAddress(DC), { kind: "page", spaceKey: null, rootPageId: "131075" });
  assert.deepEqual(readPageAddress(`${DC}&spaceKey=ENG`), { kind: "page", spaceKey: "ENG", rootPageId: "131075" });
  assert.deepEqual(readPageAddress(`${DC}&spaceKey=bad%20key`), { kind: "page", spaceKey: null, rootPageId: "131075" });
  assert.deepEqual(readPageAddress("   "), { kind: "empty" });
  const problems = {
    "100002": /full page address/,
    "javascript:alert(1)": /web address/,
    "https://wiki.acme.test/pages/viewpage.action?spaceKey=ENG&title=Home": /by its title, not its id/,
    "https://wiki.acme.test/pages/viewpage.action?pageId=12a": /by its title, not its id/,
    "https://wiki.acme.test/display/ENG/Home": /by its title, not its id/,
    "https://your-site.atlassian.net/wiki/spaces/DEMO/overview": /whole space, not of a page/,
    "https://your-site.atlassian.net/wiki/x/AbCd": /short link/,
    "https://example.test/somewhere": /No page id/,
  };
  for (const [value, expected] of Object.entries(problems)) {
    const read = readPageAddress(value);
    assert.equal(read.kind, "problem", value);
    assert.match(read.text, expected, value);
  }
});

test("a tree to add needs a valid space key: from the address, else typed by the author", () => {
  assert.deepEqual(pageTreeToAdd(readPageAddress(CLOUD), "IGNORED"), { tree: { space_key: "DEMO", root_page_id: "100002" } },
    "the address's own space wins over anything typed");
  assert.match(pageTreeToAdd(readPageAddress(DC), " ").problem, /enter the space key/);
  assert.match(pageTreeToAdd(readPageAddress(DC), "bad key").problem, /not a valid Confluence space key/);
  assert.deepEqual(pageTreeToAdd(readPageAddress(DC), " ENG "), { tree: { space_key: "ENG", root_page_id: "131075" } });
  assert.equal(pageTreeToAdd(readPageAddress(""), "ENG"), null);
  assert.equal(pageTreeToAdd(readPageAddress("nope"), "ENG"), null);
});

test("the trees are checked like the server does: some, at most 20, valid, unique, not in a whole space", () => {
  const tree = (space_key, root_page_id) => ({ space_key, root_page_id });
  assert.match(pageTreesProblem([], []), /at least one page tree/);
  assert.match(pageTreesProblem(Array.from({ length: 21 }, (_, i) => tree("ENG", String(i + 1))), []), /at most 20/);
  assert.match(pageTreesProblem([tree("ENG", "1"), tree("OPS", "1")], []), /listed twice/);
  assert.match(pageTreesProblem([tree("ENG", "1")], ["ENG"]), /already synced whole/);
  assert.match(pageTreesProblem([tree("ENG", "x1")], []), /not a space key and page id/);
  assert.match(pageTreesProblem([tree("bad key", "1")], []), /not a space key and page id/);
  assert.equal(pageTreesProblem([tree("ENG", "1"), tree("OPS", "2")], ["ARCH"]), null);
  assert.deepEqual(storedPageTrees({ page_trees: [tree("ENG", "1"), { space_key: "X" }, "y", tree("OPS", 2)] }), [tree("ENG", "1")]);
  assert.deepEqual(storedPageTrees({}), []);
});

const connector = (scope) => ({
  connector_key: "demo", kind: "confluence", scope, products: [], version: null, max_items_per_run: 100, state: "active",
  cursor: { pass_number: 1, token: null, pass_started_at: null, last_completed_at: null, completed_passes: 0 },
  schedule: { enabled: true, interval_minutes: 60, next_run_at: null }, running: false, last_run: null,
});
const TREES = [{ space_key: "DEMO", root_page_id: "100002" }, { space_key: "ENG", root_page_id: "131075" }];

test("saves send page_trees only in tree mode; stored trees open in tree mode; pausing keeps them", () => {
  const form = { ...initialForm(null), key: "team-wiki", scopeMode: "trees", pageTrees: TREES };
  assert.deepEqual(validate(form).config.page_trees, TREES);
  assert.deepEqual(validate(form).config.spaces, []);
  assert.deepEqual(validate({ ...form, keys: "ARCH" }).config.spaces, ["ARCH"], "whole spaces may be kept next to trees");
  assert.match(validate({ ...form, keys: "DEMO" }).problem, /already synced whole/);
  assert.match(validate({ ...form, pageTrees: [] }).problem, /at least one page tree/);
  const spaces = validate({ ...form, scopeMode: "spaces", keys: "ENG" }).config;
  assert.equal("page_trees" in spaces, false, "whole spaces only: the trees are not sent");
  assert.deepEqual(spaces.spaces, ["ENG"]);

  const stored = initialForm(connector({ spaces: [], page_trees: TREES }));
  assert.equal(stored.scopeMode, "trees");
  assert.deepEqual(stored.pageTrees, TREES);
  assert.equal(initialForm(connector({ spaces: ["ENG"] })).scopeMode, "spaces");
  assert.deepEqual(configOf(connector({ spaces: [], page_trees: TREES }), "paused").page_trees, TREES);
  assert.equal("page_trees" in configOf(connector({ spaces: ["ENG"] }), "paused"), false);
});

async function refusalFrom(status, detail) {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status, statusText: "", json: async () => ({ detail }) });
  try {
    await connectorsApi.configure("ws-1", "team-wiki", {});
  } catch (error) {
    return error;
  } finally { globalThis.fetch = original; }
  throw new Error("expected a refusal");
}

test("a scope refusal is explained: 409 scope_not_allowed and each 422 page-tree code; other failures are not", async () => {
  const notAllowed = scopeRefusalText(await refusalFrom(409, { state: "refused", reason: "scope_not_allowed" }));
  assert.match(notAllowed, /^Not saved: a space \(or a page tree's space\), project or table is outside the connection's allowed spaces/);
  assert.match(notAllowed, /the space of every page tree, must be one of the connection's allowed spaces/);
  const expected = {
    page_trees_invalid: /not a list of space keys and root page ids/,
    page_tree_space_invalid: /space key is not a valid Confluence space key/,
    page_tree_root_invalid: /root page id is not a page id/,
    page_tree_duplicate: /same root page is listed twice/,
    page_tree_in_listed_space: /already syncs whole; remove the tree or the space/,
    page_trees_confluence_only: /only for Confluence connectors/,
  };
  for (const [reason, pattern] of Object.entries(expected)) {
    const error = await refusalFrom(422, { state: "invalid_request", reason, field: "page_trees" });
    assert.match(scopeRefusalText(error), pattern, reason);
    assert.match(error.message, /^Refused \(page_trees\): /, reason);
  }
  assert.equal(scopeRefusalText(await refusalFrom(409, { state: "refused", reason: "connection_not_configured" })), null);
  assert.equal(scopeRefusalText(await refusalFrom(500, "boom")), null);
  assert.equal(scopeRefusalText(new Error("x")), null);
});

// ---- rendered -----------------------------------------------------------------------------------

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, encodeURIComponent, ...extra,
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

const byLabel = (view, label) => view.root.find((node) => node.type === "input" && node.props["aria-label"] === label);
const type = (view, label, value) => act(() => byLabel(view, label).props.onChange({ target: { value } }));
const buttonNamed = (view, label) => view.root.find((node) => node.type === "button" && text(node).trim() === label);
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);

test("rendered: page trees are read visibly from pasted addresses, added explicitly, several at a time, and saved", async () => {
  const { KnowledgeConnectorForm } = load("admin/components/workspaceKnowledge/KnowledgeConnectorForm.tsx");
  const saved = [];
  let view;
  act(() => {
    view = TestRenderer.create(createElement(KnowledgeConnectorForm, { editing: null, busy: false,
      // false: the form stays (as after a refused save), so the remove step below can follow.
      onSave: async (key, config) => { saved.push([key, config]); return false; }, onCancel: () => {} }));
  });
  type(view, "Connector name", "team-wiki");
  act(() => view.root.find((node) => node.type === "input" && node.props.value === "trees").props.onChange());
  assert.equal(byTestId(view, "page-tree-list").length, 0);

  type(view, "Root page address", CLOUD);
  assert.equal(byLabel(view, "Root page address").props.value, CLOUD, "the pasted address is never rewritten");
  assert.match(text(byTestId(view, "page-address-read")[0]), /page id 100002 in space DEMO\. Check them, then add the tree\./);
  assert.equal(byTestId(view, "page-tree-list").length, 0, "nothing is added before Add page tree");
  act(() => buttonNamed(view, "Add page tree").props.onClick());
  assert.equal(byLabel(view, "Root page address").props.value, "");

  type(view, "Root page address", DC);
  assert.match(text(byTestId(view, "page-address-read")[0]), /page id 131075; the address does not show the space/);
  assert.equal(buttonNamed(view, "Add page tree").props.disabled, true, "the space is asked for, not guessed");
  type(view, "Space key of the page", "ENG");
  act(() => buttonNamed(view, "Add page tree").props.onClick());

  type(view, "Root page address", CLOUD);
  assert.equal(buttonNamed(view, "Add page tree").props.disabled, true, "the same root page is not added twice");
  assert.match(text(view.root), /This root page is already listed\./);
  type(view, "Root page address", "https://your-site.atlassian.net/wiki/x/AbCd");
  assert.match(text(byTestId(view, "page-address-problem")[0]), /short link/);

  const list = byTestId(view, "page-tree-list")[0];
  assert.deepEqual(list.findAllByType("li").map((item) => text(item).replace(/\s+Remove$/, "")),
    ["Space DEMO · root page 100002 and every page below it", "Space ENG · root page 131075 and every page below it"]);
  await act(async () => { await view.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
  // JSON: the config was built in the component's realm.
  assert.equal(JSON.stringify(saved[0][1].page_trees), JSON.stringify(TREES));
  assert.equal(JSON.stringify(saved[0][1].spaces), "[]");

  // Removing a tree; switching back to whole spaces says the trees go with the next save.
  act(() => view.root.find((node) => node.type === "button" && node.props["aria-label"] === "Remove page tree 100002").props.onClick());
  assert.equal(byTestId(view, "page-tree-list")[0].findAllByType("li").length, 1);
  act(() => view.root.find((node) => node.type === "input" && node.props.value === "spaces").props.onChange());
  assert.match(text(byTestId(view, "page-trees-dropped")[0]), /Saving with whole spaces removes the 1 page tree of this connector\./);
  act(() => view.unmount());
});

test("rendered panel: a refused save shows the scope refusal next to the scope fields", async () => {
  for (const [status, detail, expected] of [
    [422, { state: "invalid_request", reason: "page_tree_in_listed_space", field: "page_trees" }, /^Not saved: a page tree is in a space the connector already syncs whole/],
    [409, { state: "refused", reason: "scope_not_allowed" }, /the space of every page tree, must be one of the connection's allowed spaces/],
  ]) {
    const fetch = async (url, init = {}) => {
      if (init.method === "PUT") return { ok: false, status, statusText: "", json: async () => ({ detail }) };
      return { ok: true, status: 200, json: async () => ({ connectors: [], may_author: true, instance_scheduler_enabled: true }) };
    };
    const { KnowledgeConnectorsPanel } = load("admin/components/workspaceKnowledge/KnowledgeConnectorsPanel.tsx", { fetch, window: { confirm: () => false } });
    let view;
    await act(async () => { view = TestRenderer.create(createElement(KnowledgeConnectorsPanel, { workspaceId: "ws-1" })); });
    assert.ok(byTestId(view, "sources-empty").length, "an empty Workspace starts with one line and Add source");
    act(() => byTestId(view, "sources-add")[0].props.onClick());
    assert.ok(byTestId(view, "knowledge-first-source").length, "the add panel says to connect a system first");
    type(view, "Connector name", "team-wiki");
    act(() => view.root.find((node) => node.type === "input" && node.props.value === "trees").props.onChange());
    type(view, "Root page address", CLOUD);
    act(() => buttonNamed(view, "Add page tree").props.onClick());
    await act(async () => { await view.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    const [refusal] = byTestId(view, "scope-refusal");
    assert.ok(refusal, `${status}: shown next to the scope`);
    assert.match(text(refusal), expected);
    assert.equal(refusal.props.role, "alert");
    act(() => view.unmount());
  }
});

test("rendered table: the scope cell lists page trees and leaves out an empty spaces line", () => {
  const { ScopeCell } = load("admin/components/workspaceKnowledge/KnowledgeConnectorCells.tsx");
  let view;
  act(() => { view = TestRenderer.create(createElement(ScopeCell, { connector: connector({ spaces: [], page_trees: TREES }) })); });
  assert.equal(text(byTestId(view, "scope-page-trees")[0]), "Page trees DEMO · 100002, ENG · 131075");
  assert.doesNotMatch(text(view.root), /Spaces/);
  act(() => view.update(createElement(ScopeCell, { connector: connector({ spaces: ["ARCH"], page_trees: TREES }) })));
  assert.match(text(view.root), /^Spaces ARCH/);
  act(() => view.update(createElement(ScopeCell, { connector: connector({ spaces: ["ARCH"] }) })));
  assert.equal(byTestId(view, "scope-page-trees").length, 0);
  act(() => view.unmount());
});
