// Knowledge › Sources keeps only what it alone manages; documents, research websites and search have their one
// home in the Knowledge menu, so the page repeats no links to them. The Admin › Knowledge pages are one page each
// (KnowledgeAdminPage).
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function load(file = "AdminWorkspaceKnowledgeTab.tsx") {
  const opened = [];
  const kept = [];
  const exports = {};
  const source = fs.readFileSync(new URL(`../../src/admin/components/workspaceKnowledge/${file}`, import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const stub = (name) => () => createElement("div", { "data-panel": name });
  vm.runInNewContext(output, {
    exports,
    require(name) {
      if (name.endsWith("useActiveWorkspace")) return { useActiveWorkspace: () => ["ws-1", () => {}] };
      if (name.endsWith("adminNavigation")) return { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) };
      if (name.endsWith("knowledgeNavigation")) return { keepWorkspaceInUrl: (id) => kept.push(id) };
      if (name.endsWith("WorkspaceScopeSelect")) return { WorkspaceScopeSelect: stub("scope") };
      if (name.endsWith("AdminHeaderSlot")) return { AdminHeaderActions: ({ children }) => children };
      const panel = name.split("/").pop();
      if (panel.startsWith("Knowledge") || panel.startsWith("AgentSandbox") || panel.startsWith("Structured")) {
        return { [panel]: stub(panel) };
      }
      return require(name);
    },
  });
  return { Tab: exports.AdminWorkspaceKnowledgeTab, Page: exports.KnowledgeAdminPage, opened, kept };
}

const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

test("Sources shows the sources only; no snapshot card (a Workspace setting), no section buttons, no search", () => {
  const { Tab } = load();
  let view;
  act(() => { view = TestRenderer.create(createElement(Tab, { projects: [{ id: "ws-1", name: "W" }] })); });
  const panels = view.root.findAll((node) => typeof node.props["data-panel"] === "string").map((node) => node.props["data-panel"]);
  assert.deepEqual(panels.filter((name) => name !== "scope"), ["KnowledgeConnectorsPanel"]);
  assert.equal(view.root.findAll((node) => node.type === "button").length, 0, "no section switch");
  act(() => view.unmount());
});

test("The local snapshot switch is a setting of the Workspace, in Settings › Workspace › Repositories", () => {
  const source = fs.readFileSync(new URL("../../src/admin/components/projectsTab/ProjectSettingsSectionContent.tsx", import.meta.url), "utf8");
  const repositories = source.slice(source.indexOf('case "repositories":'), source.indexOf('case "agents":'));
  assert.match(repositories, /<KnowledgeRepositoryPolicyPanel key=\{`\$\{project\.id\}-repositories`\} workspaceId=\{project\.id\} \/>/);
});

test("each Knowledge administration section is one Admin › Knowledge page with its panel", () => {
  const { Page } = load("KnowledgeAdminPage.tsx");
  const expected = {
    knowledgePackages: ["KnowledgePackagesPanel"], knowledgeBindings: ["KnowledgeBindingsPanel"],
    knowledgeChanges: ["KnowledgeChangesPanel"], knowledgeHandbook: ["StructuredGraphPanel", "StructuredProfilePanel"],
    knowledgeMemory: ["KnowledgeMemoryPanel"], knowledgeEpisodes: ["KnowledgeEpisodePolicyPanel"],
  };
  for (const [tab, panels] of Object.entries(expected)) {
    let view;
    act(() => { view = TestRenderer.create(createElement(Page, { tab, projects: [{ id: "ws-1", name: "W" }] })); });
    const shown = view.root.findAll((node) => typeof node.props["data-panel"] === "string").map((node) => node.props["data-panel"]);
    assert.deepEqual(shown.filter((name) => name !== "scope"), panels, tab);
    assert.equal(shown.includes("scope"), false, `${tab} has no page switch: the one global switch`);
    act(() => view.unmount());
  }
});

test("no line repeats the Knowledge menu's Documents, Research websites and Search", () => {
  const { Tab } = load();
  let view;
  act(() => { view = TestRenderer.create(createElement(Tab, { projects: [{ id: "ws-1", name: "W" }] })); });
  assert.equal(view.root.findAll((node) => node.props["aria-label"] === "Other Knowledge pages").length, 0);
  assert.doesNotMatch(text(view.root), /managed on their own pages/);
  act(() => view.unmount());
});
