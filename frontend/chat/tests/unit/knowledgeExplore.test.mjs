// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeExplore.test.mjs
// Knowledge → Explore: Relationships and Graph as two views of one page, one filter, one selection.
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
  ADMIN_AREA_CONFIGS, listAdminAreaTabRefs, resolveAdminAreaForTab, resolveAdminSidebarTab,
} from "../../src/admin/config/adminPanelAreas.ts";
import * as model from "../../src/chat/knowledge/explore/exploreModel.ts";
import * as presenter from "../../src/chat/knowledge/relationshipPresenter.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

test("one Explore entry; the old page ids are its views and stay reachable", () => {
  const find = ADMIN_AREA_CONFIGS.knowledge.groups.find((group) => group.label === "Find");
  assert.deepEqual(find.tabs.filter((tab) => !tab.hidden).map((tab) => tab.label), ["Search", "Explore"]);
  const graph = listAdminAreaTabRefs("knowledge").find((tab) => tab.id === "knowledgeGraph");
  assert.equal(graph.hidden, true);
  assert.equal(graph.adminOnly, true, "the graph stays an admin page");
  assert.equal(resolveAdminAreaForTab("knowledgeGraph"), "knowledge", "a stored Graph link still opens Knowledge");
  assert.equal(resolveAdminAreaForTab("knowledgeRelationships"), "knowledge");
  assert.equal(resolveAdminSidebarTab("knowledge", "knowledgeGraph"), "knowledgeRelationships", "Explore stays selected");
  assert.equal(model.exploreViewForTab("knowledgeGraph"), "graph");
  assert.equal(model.exploreViewForTab("knowledgeRelationships"), "list");
  assert.equal(model.exploreViewForTab(null), "list");
  assert.deepEqual(model.EXPLORE_TABS, { list: "knowledgeRelationships", graph: "knowledgeGraph" });
  assert.deepEqual(model.exploreViews(true), ["list", "graph"]);
  assert.deepEqual(model.exploreViews(false), ["list"]);
});

test("the filter and the selected entity travel in the address", () => {
  const state = { text: "PostgreSQL", type: "REMOVED", origin: "", entity: "Issuing IAM" };
  const href = model.withExploreState("https://octryx.test/chat?area=knowledge&tab=knowledgeRelationships&workspace_id=w1", state);
  const url = new URL(href);
  assert.equal(url.searchParams.get("workspace_id"), "w1");
  assert.equal(url.searchParams.has("explore_origin"), false, "empty fields leave the address");
  assert.deepEqual(model.readExploreState(url.search), state);
  assert.deepEqual(model.readExploreState("?explore_q=%20x%20"), { ...model.EMPTY_EXPLORE, text: "x" });
  const cleared = model.withExploreState(href, model.EMPTY_EXPLORE);
  assert.equal(new URL(cleared).search, "?area=knowledge&tab=knowledgeRelationships&workspace_id=w1");
});

const fact = (subject, relation, object, extra = {}) => ({
  fact: `${subject} ${relation} ${object}`, relation, subject, object, version: "1", citation: `${subject} (rev 1)`,
  source_title: subject, source_url: null, section: null, ...extra,
});

test("filtering: term, kind, origin; relationships without a source stay hidden by default", () => {
  const facts = [
    fact("APPSRV", "REQUIRES", "Issuing IAM", { origin: { kind: "confluence" } }),
    fact("Client v4", "REPLACED_BY", "APPSRV", { origin: { kind: "jira" } }),
    fact("Undertow", "REMOVED", "Spring Boot", { citation: "", source_url: null }),
  ];
  const all = { text: "", type: "", origin: "" };
  assert.equal(model.filterFacts(facts, all).length, 2);
  assert.equal(model.unsourcedCount(facts), 1);
  assert.equal(model.filterFacts(facts, all, true).length, 3);
  assert.deepEqual(model.filterFacts(facts, { ...all, text: "appsrv" }).map((entry) => entry.subject), ["APPSRV", "Client v4"]);
  assert.deepEqual(model.filterFacts(facts, { ...all, type: "REQUIRES" }).map((entry) => entry.subject), ["APPSRV"]);
  assert.deepEqual(model.filterFacts(facts, { ...all, origin: "jira" }).map((entry) => entry.subject), ["Client v4"]);
  assert.deepEqual(model.relationTypeOptions(facts).map((option) => option.label), ["removed", "replaced by", "requires"]);
  assert.deepEqual(model.originOptions(facts).map((option) => [option.label, option.count]), [["Confluence", 1], ["Jira", 1]]);
  assert.deepEqual(model.originOptions([fact("a", "X", "b")]), [], "no origin choice while the server sends none");
  assert.equal(model.concernsEntity(facts[1], "appsrv"), true);
  assert.equal(model.concernsEntity(facts[1], ""), false);
  assert.deepEqual(model.entityTypeOptions({ System: 3, Ticket: 0, Component: 1 }).map((option) => option.value), ["Component", "System"]);
  assert.equal(model.keepOfferedType("REMOVED", model.entityTypeOptions({ System: 1 })), "", "a type of the other view is dropped");
});

test("Search for this opens Search with the query and without the Explore state", () => {
  const href = model.searchForHref("https://octryx.test/chat?area=knowledge&tab=knowledgeGraph&workspace_id=w1&explore_q=x&explore_entity=APPSRV", " APPSRV ");
  const url = new URL(href);
  assert.equal(url.searchParams.get("tab"), "knowledgeLibrary");
  assert.equal(url.searchParams.get(model.SEARCH_QUERY_PARAM), "APPSRV");
  assert.equal(url.searchParams.get("workspace_id"), "w1");
  assert.equal(url.searchParams.has("explore_q"), false);
  const search = fs.readFileSync(path.join(SRC, "admin/components/workspaceKnowledge/KnowledgeSearchPanel.tsx"), "utf8");
  assert.match(search, /searchParams\.get\("q"\)/, "Search reads the hand-off");
  assert.match(search, /searchParams\.delete\("q"\)/, "and removes it from the address");
});

function loadPage(stubs, win) {
  const loadFile = (file) => {
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    vm.runInNewContext(output, {
      module, exports: module.exports, URL, URLSearchParams, window: win,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        const base = path.basename(name);
        if (stubs[base]) return stubs[base];
        if (name.startsWith(".")) {
          const target = path.resolve(path.dirname(file), name);
          if (fs.existsSync(`${target}.tsx`)) return loadFile(`${target}.tsx`);
          if (fs.existsSync(`${target}.ts`)) return loadFile(`${target}.ts`);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, "chat/knowledge/explore/KnowledgeExplorePage.tsx"));
}

function harness(href) {
  const opened = [];
  const win = {
    location: { href, search: new URL(href).search },
    history: { state: null, replaceState: (_state, _title, next) => { win.location.href = next; win.location.search = new URL(next).search; } },
  };
  const graphProps = [];
  const listProps = [];
  const { KnowledgeExplorePage } = loadPage({
    exploreModel: model,
    relationshipPresenter: presenter,
    adminNavigation: { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) },
    knowledgeNavigation: { keepWorkspaceInUrl: () => {} },
    KnowledgeCitation: { KnowledgeCitation: () => null, readableCitation: (value) => value.replace(/\(rev \d+\)/g, "").trim() },
    AdminEntityGraphViews: { AdminEntityGraphViews: (props) => { graphProps.push(props); return createElement("div", { id: "graph" }); } },
    KnowledgeRelationshipsPanel: { KnowledgeRelationshipsPanel: (props) => { listProps.push(props); return createElement("div", { id: "list" }); } },
  }, win);
  return { KnowledgeExplorePage, opened, win, graphProps, listProps };
}

const props = (view, isAdmin = true) => ({ workspaceId: "w1", view, isAdmin, projects: [], onWorkspaceChange: () => {} });
const buttonsOf = (view) => view.root.findAllByType("button").map((button) => [].concat(button.props.children).filter((part) => typeof part === "string").join(""));

test("the view switch opens the other page id and keeps the selected entity", () => {
  const { KnowledgeExplorePage, opened, win, graphProps, listProps } =
    harness("https://octryx.test/chat?area=knowledge&tab=knowledgeRelationships&explore_entity=APPSRV");
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeExplorePage, props("list"))); });
  assert.ok(view.root.findAllByProps({ id: "list" }).length);
  assert.equal(listProps.at(-1).entity, "APPSRV", "the entity from the address is selected");
  assert.ok(view.root.findAllByProps({ "data-testid": "explore-entity" }).length, "its side panel is open");
  const graphButton = view.root.findAll((node) => node.type === "button" && node.props.role === "tab" && node.props.id === "explore-view-tab-graph")[0];
  assert.ok(graphButton, "List | Graph are segments");
  act(() => graphButton.props.onClick());
  assert.deepEqual(opened, ["knowledgeGraph"]);
  assert.equal(new URL(win.location.href).searchParams.get("explore_entity"), "APPSRV", "the entity stays in the address");
  act(() => view.update(createElement(KnowledgeExplorePage, props("graph"))));
  assert.equal(graphProps.at(-1).selectName, "APPSRV", "the graph opens the same entity");
  act(() => graphProps.at(-1).onSearchFor("APPSRV"));
  assert.equal(opened.at(-1), "knowledgeLibrary");
  assert.equal(new URL(win.location.href).searchParams.get("q"), "APPSRV");
});

test("without admin rights there is no Graph view, and a Graph link shows the list", () => {
  const { KnowledgeExplorePage } = harness("https://octryx.test/chat?area=knowledge&tab=knowledgeGraph");
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeExplorePage, props("graph", false))); });
  assert.ok(view.root.findAllByProps({ id: "list" }).length);
  assert.equal(buttonsOf(view).includes("Graph"), false);
});
