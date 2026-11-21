// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/explorePilot.test.mjs
//
// Design-system pilot (product inventory): Knowledge › Explore's list is a compact table, one row per
// relationship (Subject · Relationship · Object · Version · Source); a row or a name opens the entity in the side
// panel over the dimmed list, with "Open as page"; List | Graph are segments and keep the selection; an empty
// Workspace shows one line with one action.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { entityPageHref, isEntityPage, sourceText } from "../../src/chat/knowledge/explore/exploreModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (node == null ? "" : typeof node === "string" ? node : Array.isArray(node) ? node.map(text).join("")
  : (node.children || []).map(text).join(""));

function loader(extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Intl, setTimeout, clearTimeout,
      FormData: class FormData {}, ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.endsWith("/adminNavigation")) return { useAdminNavigation: () => ({ openAdminTab: (tab) => extra.opened?.push(tab) }) };
        if (name.endsWith("/AdminEntityGraphViews")) return { AdminEntityGraphViews: (props) => { extra.graphProps?.push(props); return createElement("div", { id: "graph" }); } };
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return (relative) => loadFile(path.join(SRC, relative));
}

const FACTS = [
  { fact: "APPSRV requires Java SE 17", relation: "REQUIRES", subject: "APPSRV", object: "Java SE 17", version: "4.4",
    citation: "Admin guide (rev 1, p. 702, § 4.4 Database)", source_title: "Admin guide", source_url: null, section: null },
  { fact: "Batch runner requires PostgreSQL", relation: "REQUIRES", subject: "Batch runner", object: "PostgreSQL", version: "4.4",
    citation: "Ops handbook (rev 3, p. 12)", source_title: "Ops handbook", source_url: "https://wiki.test/ops", section: null },
];

function harness(href) {
  const opened = [];
  const graphProps = [];
  const win = {
    location: { href, search: new URL(href).search, origin: "https://octryx.test" },
    history: { state: null, replaceState: (_s, _t, next) => { win.location.href = next; win.location.search = new URL(next).search; } },
    addEventListener() {}, removeEventListener() {},
  };
  const fetch = async (url) => {
    const u = String(url);
    const body = u.endsWith("/products") ? { products: { "Acme Orders": ["4.3", "4.4"] } }
      : u.endsWith("/graph") ? { episodes: 5, pending_revisions: 0, readable: true, extractable: true }
        : u.endsWith("/changes") ? { state: "ok", versions: ["4.4"], episodes: 5, facts: FACTS, counts: {} } : {};
    return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => body, text: async () => JSON.stringify(body) };
  };
  const doc = { activeElement: null, addEventListener() {}, removeEventListener() {} };
  const load = loader({ fetch, window: win, document: doc, opened, graphProps });
  return { KnowledgeExplorePage: load("chat/knowledge/explore/KnowledgeExplorePage.tsx").KnowledgeExplorePage, opened, graphProps, win };
}
const props = (view, isAdmin = true) => ({ workspaceId: "w1", view, isAdmin, projects: [], onWorkspaceChange: () => {} });
const byTestId = (view, id) => view.root.findAll((node) => node.props?.["data-testid"] === id);

async function render(href, view = "list") {
  const h = harness(href);
  let tree;
  await act(async () => { tree = TestRenderer.create(createElement(h.KnowledgeExplorePage, props(view))); });
  for (let i = 0; i < 5; i += 1) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  return { ...h, tree };
}

test("model: the source line drops the revision; Open as page is a flag in the address", () => {
  assert.equal(sourceText(FACTS[0], (value) => value.replace(/rev \d+,\s*/, "")), "Admin guide (p. 702, § 4.4 Database)");
  assert.equal(sourceText({ citation: "", source_title: "Handbook" }, (value) => value), "Handbook");
  const page = entityPageHref("https://octryx.test/chat?tab=knowledgeRelationships", "APPSRV");
  assert.equal(new URL(page).searchParams.get("explore_entity"), "APPSRV");
  assert.ok(isEntityPage(new URL(page).search));
  assert.equal(isEntityPage(new URL(entityPageHref(page, "", false)).search), false);
});

test("the list is a compact table, one row per relationship with Subject · Relationship · Object · Version · Source", async () => {
  const { tree } = await render("https://octryx.test/chat?area=knowledge&tab=knowledgeRelationships");
  const table = tree.root.findAll((node) => node.type === "table" && node.props["aria-label"] === "Relationships")[0];
  assert.ok(table, "a table, not a card list");
  const headers = table.findAllByType("th").map((th) => text(th.children));
  assert.deepEqual(headers, ["Subject", "Relationship", "Object", "Version", "Source"]);
  const rows = table.findAll((node) => node.type === "tr" && node.props["data-row-key"]);
  assert.equal(rows.length, 2);
  const first = text(rows[0].children);
  assert.match(first, /APPSRV/); assert.match(first, /Java SE 17/); assert.match(first, /4\.4/);
  assert.doesNotMatch(first, /rev 1/, "no internal revision in the source");
});

test("a row or a name opens the entity in the side panel; ✕ closes it; Open as page shows it as a page", async () => {
  const { tree, win } = await render("https://octryx.test/chat?area=knowledge&tab=knowledgeRelationships");
  const row = tree.root.findAll((node) => node.type === "tr" && node.props["data-row-key"])[1];
  await act(async () => row.props.onClick());
  let panel = byTestId(tree, "explore-entity")[0];
  assert.ok(panel, "the side panel is open");
  assert.equal(panel.props.role, "dialog");
  assert.match(text(panel.children), /Batch runner/);
  assert.ok(byTestId(tree, "explore-entity-backdrop").length, "over the dimmed list");
  const openPage = byTestId(tree, "explore-entity-open-page")[0];
  assert.ok(new URL(openPage.props.href).searchParams.get("explore_entity_page"), "Open as page has its address");
  await act(async () => byTestId(tree, "explore-entity-close")[0].props.onClick());
  assert.equal(byTestId(tree, "explore-entity").length, 0, "✕ closes it");
  assert.equal(new URL(win.location.href).searchParams.get("explore_entity"), null);

  const name = tree.root.findAll((node) => node.type === "button" && text(node.children) === "PostgreSQL")[0];
  await act(async () => name.props.onClick({ stopPropagation() {} }));
  assert.match(text(byTestId(tree, "explore-entity")[0].children), /PostgreSQL/, "a name opens that entity, not the subject");

  const asPage = await render("https://octryx.test/chat?area=knowledge&tab=knowledgeRelationships&explore_entity=APPSRV&explore_entity_page=1");
  panel = byTestId(asPage.tree, "explore-entity")[0];
  assert.equal(panel.type, "section", "as a page: no dialog, no backdrop");
  assert.equal(byTestId(asPage.tree, "explore-entity-backdrop").length, 0);
});

test("List | Graph are segments and the selected entity stays when switching", async () => {
  const { tree, opened, win } = await render("https://octryx.test/chat?area=knowledge&tab=knowledgeRelationships&explore_entity=APPSRV");
  const tabs = tree.root.findAll((node) => node.type === "button" && node.props.role === "tab");
  assert.deepEqual(tabs.map((tab) => text(tab.children)), ["List", "Graph"]);
  await act(async () => tabs[1].props.onClick());
  assert.deepEqual(opened, ["knowledgeGraph"]);
  assert.equal(new URL(win.location.href).searchParams.get("explore_entity"), "APPSRV");
  const graphPage = await render(win.location.href.replace("knowledgeRelationships", "knowledgeGraph"), "graph");
  assert.equal(graphPage.graphProps.at(-1).selectName, "APPSRV", "the graph opens the same entity");
  assert.equal(graphPage.tree.root.findAll((node) => node.props?.role === "tab" && node.props["aria-selected"] === true)
    .map((tab) => text(tab.children)).join(), "Graph");
});

test("empty Workspace: one line with one action, no table, no box", async () => {
  const opened = [];
  const fetch = async (url) => {
    const u = String(url);
    const body = u.endsWith("/products") ? { products: {} } : u.endsWith("/graph") ? { episodes: 0, pending_revisions: 0, readable: true, extractable: true } : {};
    return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => body, text: async () => JSON.stringify(body) };
  };
  const load = loader({ fetch, window: { location: { origin: "https://octryx.test" } } });
  const { KnowledgeRelationshipsPanel } = load("chat/knowledge/KnowledgeRelationshipsPanel.tsx");
  let tree;
  await act(async () => { tree = TestRenderer.create(createElement(KnowledgeRelationshipsPanel, {
    workspaceId: "ws-empty", filter: { text: "", type: "", origin: "" }, entity: "",
    onSelectEntity() {}, onFacts() {}, onBusy() {}, onOpen: (tab) => opened.push(tab) })); });
  await act(async () => {});
  const line = byTestId(tree, "empty-line");
  assert.equal(line.length, 1);
  assert.match(text(line[0].children), /No relationships extracted in this workspace yet/);
  assert.equal(tree.root.findAllByType("table").length, 0);
  const buttons = tree.root.findAllByType("button");
  assert.deepEqual(buttons.map((button) => text(button.children)), ["Open Sources"]);
  act(() => buttons[0].props.onClick());
  assert.deepEqual(opened, ["workspaceKnowledge"]);
});
