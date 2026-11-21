// One visible Workflows entry; the related administration stays reachable.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createContext, createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as areas from "../../src/admin/config/adminPanelAreas.ts";
import * as administration from "../../src/admin/components/workflowSurfaces/workflowAdministration.ts";
import * as pageHeader from "../../src/layout/PageHeader.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function load(path, mocks) {
  const exports = {};
  const source = fs.readFileSync(new URL(`../../src/admin/${path}`, import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports,
    window: globalThis.window,
    require: (name) => {
      const key = name.split("/").at(-1);
      if (key.endsWith(".css")) return {};
      return key in mocks ? mocks[key] : require(name);
    },
  });
  return exports;
}
const text = (node) => (typeof node === "string" ? node : node.children.map(text).join(""));
const ADVANCED = ["scenarios"];

test("the final nav shows exactly the approved entries, with one Workflows entry and no separate Canvas", () => {
  // The builder part of the one Agents menu (Clients · Build · Rules · Reference); the Canvas is the
  // Workflows page's main view, no reference page.
  const groups = areas.ADMIN_AREA_CONFIGS.workflows.groups.map((group) => [
    group.label,
    group.tabs.filter((ref) => !ref.hidden).map((ref) => ref.label),
  ]);
  // Instructions and Effective setup left the navigation for Admin › Rules; their links still open them.
  assert.deepEqual(groups, [
    ["Build", ["Agents", "Workflows", "Skills"]],
    ["Reference", ["Tools"]],
  ]);
  // Agents stay the one canonical agent place.
  const sidebar = areas.listAdminAreaTabRefs("workflows").filter((ref) => !ref.hidden).map((ref) => ref.id);
  assert.deepEqual(sidebar.filter((id) => /agent/i.test(id)), ["agents"]);
});

test("advanced pages keep their route IDs and deep links and select Workflows in the sidebar", () => {
  for (const tab of ADVANCED) {
    assert.equal(areas.resolveAdminAreaForTab(tab), "workflows");
    assert.equal(areas.resolveAdminAreaTab("workflows", tab), tab, `${tab} still opens by deep link`);
    assert.equal(areas.resolveAdminAreaTab("workflows", tab, false), tab, `${tab} visibility is unchanged for members`);
    assert.equal(areas.resolveAdminSidebarTab("workflows", tab), "workflowList");
  }
  assert.equal(areas.resolveAdminSidebarTab("workflows", "workflowList"), "workflowList");
  assert.equal(areas.resolveAdminSidebarTab("workflows", "agents"), "agents");
  // An unknown page id names no page: the area opens on its default page.
  for (const retired of ["flowBuilder", "workflowDefinitions", "movedItems"]) {
    assert.equal(areas.resolveAdminAreaTab("workflows", retired), areas.ADMIN_AREA_CONFIGS.workflows.defaultTab);
  }
});

test("the advanced list names every hidden page plainly", () => {
  const pages = administration.workflowAdministrationPages();
  assert.deepEqual(pages.map((page) => page.tab), ADVANCED);
  for (const page of pages) assert.ok(page.purpose.length > 20, `${page.tab} has a purpose`);
  assert.equal(pages.some((page) => /published definitions/i.test(page.title)), false);
});

test("the advanced section is collapsed and opens each page through the admin navigation", () => {
  const opened = [];
  const navigation = { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) };
  const { WorkflowAdministrationSection } = load("components/workflowSurfaces/WorkflowAdministrationSection.tsx", {
    adminNavigation: navigation,
    workflowAdministration: administration,
  });
  let view;
  act(() => {
    view = TestRenderer.create(createElement(WorkflowAdministrationSection));
  });
  const details = view.root.findByType("details");
  assert.equal(details.props.open, undefined, "collapsed by default");
  assert.equal(text(view.root.findByType("summary")), "Advanced workflow administration");
  const hint = text(view.root.findByProps({ className: "admin-panel__hint" }));
  assert.equal(hint, "Manage scenarios.");
  assert.doesNotMatch(hint, /never|none of these|can run/i);
  for (const button of view.root.findAllByType("button")) act(() => button.props.onClick());
  assert.deepEqual(opened, ADVANCED);
  act(() => view.unmount());
});

test("an advanced page offers the way back to Workflows", () => {
  const opened = [];
  const { AreaPurpose } = load("components/workflowSurfaces/AreaPurpose.tsx", {
    adminNavigation: { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) },
  });
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AreaPurpose, { purpose: "Scenarios", back: administration.WORKFLOWS_HOME }));
  });
  const back = view.root.findAllByType("button").find((button) => text(button) === "← Workflows");
  act(() => back.props.onClick());
  assert.deepEqual(opened, ["workflowList"]);
  act(() => view.unmount());
});

test("the shell keeps Workflows selected while an advanced page is open", () => {
  const entry = (id, label) => ({ id, label, icon: null });
  const groups = [
    { label: "Agents", tabs: [entry("agents", "Agents")] },
    { label: "Workflows", tabs: [entry("workflowList", "Workflows")] },
  ];
  const { AdminPanelShell } = load("components/AdminPanelShell.tsx", {
    adminPanelAreas: areas,
    adminPanelAreaTabGroups: { getAdminAreaTabGroups: () => groups },
    adminHeaderSlotContext: { AdminHeaderSlotContext: createContext(null) },
    pagePurpose: { ADMIN_PAGE_PURPOSE: {} },
    PageHeader: pageHeader,
    AdminExternalNav: { AdminExternalNavButtons: () => null, externalOnlyGroups: () => [] },
    AdminEntryTabs: { AdminEntryTabs: () => null },
    activeWorkspaceName: { useActiveWorkspaceName: () => "", areaWithWorkspace: (area) => area },
  });
  const opened = [];
  let view;
  act(() => {
    view = TestRenderer.create(
      createElement(AdminPanelShell, { area: "workflows", tab: "scenarios", setTab: (tab) => opened.push(tab), currentTabLabel: "Scenarios" }, "body"),
    );
  });
  const workflows = view.root.findAllByType("button").find((button) => text(button) === "Workflows");
  assert.match(workflows.props.className, /admin-panel__tab--active/);
  assert.equal(workflows.props["aria-current"], "location");
  const agents = view.root.findAllByType("button").find((button) => text(button) === "Agents");
  assert.doesNotMatch(agents.props.className, /admin-panel__tab--active/);
  assert.match(text(view.root.findByProps({ className: "page-header__eyebrow" })), /Workflows/);
  act(() => workflows.props.onClick());
  assert.deepEqual(opened, ["workflowList"]);
  act(() => view.update(createElement(AdminPanelShell, { area: "workflows", tab: "workflowList", setTab() {}, currentTabLabel: "Workflows" }, "body")));
  assert.equal(view.root.findAllByType("button").find((button) => text(button) === "Workflows").props["aria-current"], "page");
  act(() => view.unmount());
});
