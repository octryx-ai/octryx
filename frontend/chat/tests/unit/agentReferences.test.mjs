// "Used by" on the canonical agent page: presenter and rendered section.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as model from "../../src/admin/components/agentsTab/agentReferencesModel.ts";
import { flowEditorHref } from "../../src/admin/editorLinks.ts";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const WORKFLOW = {
  kind: "workflow", id: "f1", name: "Release review", workspace_id: null, workspace_name: null,
  reference_state: "published", revision: 3, latest_revision: 3, latest_references_agent: true,
};
const DRAFT = {
  kind: "workflow", id: "f2", name: "Triage", workspace_id: "w1", workspace_name: "Petclinic",
  reference_state: "current_draft", revision: 2, latest_revision: 2, latest_references_agent: true,
};
const payload = (overrides = {}) => ({ agent_id: "a", workflows: [], truncated: false, ...overrides });

function loadView() {
  const exports = {};
  const source = fs.readFileSync(
    new URL("../../src/admin/components/agentsTab/AgentReferencesSection.tsx", import.meta.url), "utf8",
  );
  const output = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(output, {
    exports,
    require: (name) => {
      if (name.endsWith("agentReferencesModel")) return model;
      if (name.endsWith("useAgentReferences")) return { useAgentReferences: () => ({ state: "loading", payload: null }) };
      return require(name);
    },
  });
  return exports.AgentReferencesView;
}

function render(props) {
  const View = loadView();
  let view;
  act(() => { view = TestRenderer.create(createElement(View, props)); });
  return view;
}

const texts = (view) => view.root.findAll((node) => typeof node.type === "string")
  .flatMap((node) => node.children.filter((child) => typeof child === "string")).join(" ");

test("state labels say in plain words which version uses the agent", () => {
  assert.equal(model.referenceStateLabel(WORKFLOW), "Published version 3");
  assert.equal(model.referenceStateLabel(DRAFT), "Current draft, version 2 (not published)");
  assert.equal(model.referenceStateLabel({ ...DRAFT, reference_state: "in_review" }), "In review, version 2");
  assert.equal(model.referenceStateLabel({ ...WORKFLOW, reference_state: "older_revision_only" }), "Only an older version 3");
  assert.equal(model.referenceWorkspaceLabel(WORKFLOW), "Global");
  assert.equal(model.referenceWorkspaceLabel(DRAFT), "Petclinic");
  assert.equal(model.referenceWorkspaceLabel({ workspace_id: "w2", workspace_name: null }), "Workspace not visible to you");
  assert.equal(model.agentReferencesUrl("a/b"), "/admin/chat/api/panel/agents/a%2Fb/references");
});

test("a published version dropped by a newer draft says the link opens that draft, not the referencing version", () => {
  const moved = { ...WORKFLOW, revision: 1, latest_revision: 3, latest_references_agent: false };
  assert.equal(model.referenceStateLabel(moved), "Published version 1");
  assert.equal(model.referenceDestinationLabel(moved), "Opens the latest version 3, which no longer uses this agent");
  const row = model.referenceRow(moved);
  assert.equal(row.href, flowEditorHref("f1"));
  assert.equal(row.linkLabel, "Open workflow Release review at its latest version 3");

  const older = { ...DRAFT, reference_state: "published", revision: 1, latest_revision: 2, latest_references_agent: true };
  assert.equal(model.referenceDestinationLabel(older), "Opens the latest version 2, which also uses this agent");
  assert.equal(model.referenceDestinationLabel(WORKFLOW), "Opens version 3, the latest");
});

test("rows link to the existing editor through the shared editor links", () => {
  const groups = model.agentReferenceGroups(payload({ workflows: [WORKFLOW, DRAFT] }));
  assert.equal(groups.workflows[0].href, flowEditorHref("f1"));
  assert.equal(groups.workflows[1].href, flowEditorHref("f2"));
  assert.equal(groups.empty, false);
  assert.equal(model.agentReferenceGroups(null).empty, true);
});

test("the section renders the workflows with editor links and no total", () => {
  const view = render({ state: "ready", payload: payload({ workflows: [WORKFLOW, DRAFT] }) });
  const links = view.root.findAllByType("a");
  assert.deepEqual(links.map((link) => link.props.href), [flowEditorHref("f1"), flowEditorHref("f2")]);
  assert.deepEqual(links.map((link) => link.props["aria-label"]), [
    "Open workflow Release review at its latest version 3",
    "Open workflow Triage at its latest version 2",
  ]);
  const text = texts(view);
  assert.match(text, /Workflows/);
  assert.match(text, /Global/);
  assert.match(text, /Published version 3/);
  assert.match(text, /Opens version 3, the latest/);
  assert.doesNotMatch(text, /\btotal\b|\(\d+\)/i);
  assert.equal(view.root.findAll((node) => node.props?.role === "note").length, 0);
  act(() => view.unmount());
});

test("an unused agent shows the truthful empty state; a truncated list says so", () => {
  const empty = render({ state: "ready", payload: payload() });
  assert.match(texts(empty), /No workflow you can see uses this agent\./);
  assert.equal(empty.root.findAllByType("table").length, 0);
  act(() => empty.unmount());

  const partial = render({ state: "ready", payload: payload({ workflows: [WORKFLOW], truncated: true }) });
  assert.equal(partial.root.findByProps({ role: "note" }).children.join(""), model.TRUNCATED_TEXT);
  act(() => partial.unmount());
});

test("loading and error states never show lists", () => {
  const loading = render({ state: "loading", payload: null });
  assert.equal(loading.root.findByProps({ role: "status" }).children.join(""), "Reading where this agent is used…");
  act(() => loading.unmount());

  const failed = render({ state: "error", payload: null });
  assert.match(failed.root.findByProps({ role: "alert" }).children.join(""), /Could not read where this agent is used/);
  assert.equal(failed.root.findAllByType("a").length, 0);
  act(() => failed.unmount());
});
