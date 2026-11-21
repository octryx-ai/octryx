// Graph stage: selecting an entity docks its details beside the graph without a page jump; Close and
// Escape return to the graph with focus on the list item; sources and self references stay (C3 rework,
// graph redesign).
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as links from "../../src/chat/evidence/answerSourceLinks.ts";
import * as api from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeApi.ts";
import * as request from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeRequest.ts";
import * as reading from "../../src/admin/components/entityGraph/entityGraphReading.ts";
import * as matchesModule from "../../src/admin/components/entityGraph/entityGraphMatches.ts";
import * as detailModel from "../../src/admin/components/entityGraph/entityGraphDetailModel.ts";
import * as types from "../../src/admin/components/entityGraph/entityGraphTypes.ts";
import * as kgLayout from "../../src/admin/components/entityGraph/kgLayout.ts";
import * as kgView from "../../src/admin/components/entityGraph/kgView.ts";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const dir = new URL("../../src/admin/components/entityGraph/", import.meta.url);
function load(file, modules) {
  const exports = {};
  const source = fs.readFileSync(new URL(file, dir), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  vm.runInNewContext(output, {
    exports, window: { location: { origin: "https://local.test" } },
    require(name) {
      const key = name.split("/").pop();
      if (key.endsWith(".css")) return {};
      return modules[key] ?? require(name);
    },
  });
  return exports;
}
const Citation = load("EntityGraphCitation.tsx", { answerSourceLinks: links, workspaceKnowledgeApi: api, workspaceKnowledgeRequest: request });
const Relations = load("EntityGraphDetailRelations.tsx", { EntityGraphCitation: Citation });
const Detail = load("AdminEntityGraphDetailPanel.tsx", {
  entityGraphTypes: types, entityGraphReading: reading, entityGraphDetailModel: detailModel,
  EntityGraphCitation: Citation, EntityGraphDetailRelations: Relations,
});
const List = load("EntityGraphEntityList.tsx", { entityGraphMatches: matchesModule, entityGraphReading: reading });
const { EntityGraphCanvas } = load("EntityGraphCanvas.tsx", {
  entityGraphReading: reading, AdminEntityGraphDetailPanel: Detail, EntityGraphEntityList: List, kgLayout, kgView,
});

const positioned = [
  { id: "j2", display_name: "Jackson 2", node_type: "entity", x: 0, y: 0, radius: 10, degree: 2 },
  { id: "sb", display_name: "Spring Boot", node_type: "entity", x: 50, y: 0, radius: 10, degree: 1 },
];
const evidence = { source_id: "src", revision_id: "rev", citation: "Spring Boot reference", evidence_key: "k1" };
const visibleEdges = [
  { id: "e1", source: "j2", target: "sb", edge_type: "HAS_PROPERTIES_UNDER", description: "Jackson 2 properties live under spring.jackson", ...evidence },
  { id: "e2", source: "j2", target: "j2", edge_type: "SAME_AS", description: "Jackson 2 is the same as Jackson", ...evidence },
];
const relation = (peer_id, peer_name, direction, edge_type, description) =>
  ({ peer_id, peer_name, peer_type: "entity", direction, edge_type, description, ...evidence });
const detail = {
  id: "j2", state: "ok", workspace_id: "w", display_name: "Jackson 2", node_type: "entity", description: "",
  trust_level: "extracted", status: "extracted", truncated: false, properties: {}, source_refs: [], aliases: [], claims: [],
  relations: [
    relation("sb", "Spring Boot", "out", "HAS_PROPERTIES_UNDER", "Jackson 2 properties live under spring.jackson"),
    relation("j2", "Jackson 2", "out", "SAME_AS", "Jackson 2 is the same as Jackson"),
    relation("cbor", "CBOR", "in", "EXTENDS", "CBOR extends Jackson 2"),
  ],
};

function render(overrides = {}) {
  const calls = { select: [], focus: [], close: 0, headingFocus: [], itemFocus: [], scrollIntoView: 0 };
  const items = positioned.map((node) => ({ dataset: { entityId: node.id }, offsetParent: {}, focus: (options) => calls.itemFocus.push([node.id, options]) }));
  const props = {
    workspaceId: "w", nodes: positioned, edges: visibleEdges, slots: new Map([["entity", 1]]),
    positions: new Map(positioned.map((node) => [node.id, { x: node.x, y: node.y, r: node.radius, cluster: "entity", hub: false }])),
    selectedId: "", neighborIds: new Set(), matches: new Set(), bases: new Map(), query: "", searching: false,
    detail: null, detailLoading: false,
    onSelect: (id) => calls.select.push(id), onFocus: (id) => calls.focus.push(id), onClose: () => { calls.close += 1; },
    ...overrides,
  };
  const createNodeMock = (element) => {
    const scrollIntoView = () => { calls.scrollIntoView += 1; };
    if (element.type === "h3") return { focus: (options) => calls.headingFocus.push(options), scrollIntoView };
    if (element.type === "div") return { querySelectorAll: () => items, scrollIntoView };
    return { scrollIntoView };
  };
  let view;
  act(() => { view = TestRenderer.create(createElement(EntityGraphCanvas, props), { createNodeMock }); });
  return { view, calls, props, rerender: (next) => act(() => view.update(createElement(EntityGraphCanvas, { ...props, ...next }))) };
}
const text = (view) => JSON.stringify(view.toJSON());
const textOf = (node) => (typeof node === "string" ? node : node.children.map(textOf).join(""));
const button = (view, label) => view.root.findAll((node) => node.type === "button" && textOf(node).includes(label))[0];
// Objects created inside the vm realm compare by JSON, not by prototype.
const plain = (value) => JSON.parse(JSON.stringify(value));

const stage = (view) => view.root.findAll((node) => node.type === "div" && node.props.className === "kg-stage")[0];

test("without a selection the stage is the graph alone; the entity list (full names) is the reading path", () => {
  const { view, calls } = render({ listOpen: true });
  assert.equal(stage(view).props["data-detail"], undefined);
  assert.equal(view.root.findAll((node) => node.type === "h3").length, 0);
  act(() => button(view, "Jackson 2").props.onClick());
  assert.deepEqual(calls.select, ["j2"]);
  act(() => view.unmount());
});

test("a selection docks the details beside the graph, focused, without scrolling the page", () => {
  const { view, calls } = render({ selectedId: "j2", detail });
  assert.equal(stage(view).props["data-detail"], true);
  assert.equal(view.root.findByType("h3").children[0], "Jackson 2");
  assert.deepEqual(plain(calls.headingFocus), [{ preventScroll: true }]);
  assert.equal(calls.scrollIntoView, 0);
  const output = text(view);
  assert.equal(output.match(/Extracted · not reviewed/g).length, 1);
  assert.doesNotMatch(output, /"extracted"/, "status equal to trust is not shown again");
  assert.match(output, /3 available relationships in this neighbourhood · 2 shown in the current view/);
  const relationType = view.root.findAll((node) => node.props.title === "HAS_PROPERTIES_UNDER")[0];
  assert.equal(relationType.children[0], "has properties under");
  assert.match(output, /refers to itself \(same entity on both ends\)/);
  const outside = view.root.findAll((node) => node.props.className === "entity-graph__relation-scope");
  assert.deepEqual(outside.map(textOf), ["not in this view"], "only the stored-only CBOR relationship is marked");
  const captured = view.root.findAllByType("a").filter((anchor) => anchor.children[0] === "Open captured source");
  assert.equal(captured.length, 3);
  assert.equal(captured[0].props.href, "/api/v1/workspaces/w/knowledge/sources/src/revisions/rev/original");
  act(() => view.unmount());
});

test("an entity in this view is selected; one outside it loads its neighbourhood", () => {
  const { view, calls } = render({ selectedId: "j2", detail });
  act(() => button(view, "Spring Boot").props.onClick());
  act(() => button(view, "CBOR").props.onClick());
  act(() => button(view, "Expand").props.onClick());
  assert.deepEqual(calls.select, ["sb"]);
  assert.deepEqual(calls.focus, ["cbor", "j2"]);
  act(() => view.unmount());
});

test("Close and Escape return to the graph with focus on the entity's list item", () => {
  const first = render({ selectedId: "j2", detail, listOpen: true });
  act(() => first.view.root.findByProps({ "aria-label": "Close details" }).props.onClick());
  assert.equal(first.calls.close, 1);
  first.rerender({ selectedId: "", detail: null });
  assert.deepEqual(plain(first.calls.itemFocus), [["j2", { preventScroll: true }]]);
  assert.equal(stage(first.view).props["data-detail"], undefined);
  act(() => first.view.unmount());

  const second = render({ selectedId: "j2", detail });
  act(() => stage(second.view).props.onKeyDown({ key: "Escape", preventDefault() {} }));
  assert.equal(second.calls.close, 1);
  act(() => second.view.unmount());
});

test("matched entities say why they matched", () => {
  const { view } = render({
    searching: true, query: "Jackson", matches: new Set(["j2", "sb"]), bases: new Map([["j2", "name"], ["sb", "statement"]]),
  });
  const output = text(view);
  assert.match(output, /Name contains “Jackson”/);
  assert.match(output, /A relationship statement mentions “Jackson”/);
  assert.match(output, /Matches \(","2",/);
  act(() => view.unmount());
});
