// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminConnectionsExternalViews.test.mjs
// Admin › Connections › Repositories and Jira write-back: the two views live in another component
// and open there. A seam test through the real app switch (AppContainerView), the real Admin area
// (AdminAreaWorkspace), the real shell and its views (AdminPanelShell, AdminEntryTabs): selecting the segment leaves
// the Connections list and shows the repositories page (Coding › Repositories), resp. the write-back page.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createContext, createElement, Fragment, useState } from "react";
import TestRenderer from "react-test-renderer";

import { codingWorkspaceView } from "../../src/chat/workspaceDestinations.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");

// Loads a source file with its real relative imports, except the modules named in `mocks` (by file name).
function load(relative, mocks, globals = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    vm.runInNewContext(output, {
      exports, console, Promise, ...globals,
      require: (name) => {
        const key = name.split("/").at(-1);
        if (key.endsWith(".css")) return {};
        if (key in mocks) return mocks[key];
        if (!name.startsWith(".")) return require(name);
        const base = path.resolve(path.dirname(file), name);
        return loadFile([".ts", ".tsx"].map((ext) => base + ext).find((candidate) => fs.existsSync(candidate)));
      },
    });
    return exports;
  };
  return loadFile(path.join(SRC, relative));
}

const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));
const stub = (testId) => (props) => createElement("section", { "data-testid": testId, "data-props": props });
const passThrough = ({ children }) => createElement(Fragment, null, children);

// The Admin panel as the area shows it on Admin › Connections: the real shell with the Connections list as its page.
let AdminPanelShell;
function AdminPanelOnConnections({ externalNav, isAdmin }) {
  return createElement(AdminPanelShell, {
    area: "admin", tab: "adminConnections", setTab() {}, currentTabLabel: "Connections", isAdmin, externalNav,
  }, createElement("section", { "data-testid": "connections-page" }, "All 6 · Working 6"));
}

const shellMocks = {
  adminPanelAreaTabGroups: { getAdminAreaTabGroups: () => [] },
  activeWorkspaceName: { useActiveWorkspaceName: () => "", areaWithWorkspace: (area) => area },
  usePageHelp: { openPageHelp() {}, usePageHelp: () => [false, () => {}], useHelpPage: () => null },
  adminHeaderSlotContext: { AdminHeaderSlotContext: createContext(null) },
};
AdminPanelShell = load("admin/components/AdminPanelShell.tsx", shellMocks).AdminPanelShell;

// The address the app reads (the way back to Admin); an area switch writes the target's fields into it.
const fakeWindow = { location: { search: "" } };
const { AppContainerView } = load("chat/AppContainerView.tsx", {
  ...shellMocks,
  AdminPanelContainer: { AdminPanelContainer: AdminPanelOnConnections },
  AreaRail: { AreaRail: () => null },
  CompactAreaMenu: { CompactAreaMenu: () => null },
  AgentsAreaWorkspace: { AgentsAreaWorkspace: stub("agents-area") },
  AgentsAreaNav: { AgentsNavIcon: () => null },
  PageHelpDrawer: { PageHelpDrawer: () => null },
  SidebarShell: { SidebarShell: () => null },
  WorkspaceMainArea: { WorkspaceMainArea: () => null },
  AppContainerOverlays: { AppContainerOverlays: () => null },
  CodingWorkspaceEntry: { CodingWorkspaceEntry: stub("coding-area") },
  WorkAreaWorkspace: { WorkAreaWorkspace: stub("work-area") },
  PersonalSettingsWorkspace: { PersonalSettingsWorkspace: () => null },
  SetupGuidePage: { SetupGuidePage: () => null },
  CompanionHost: { CompanionHost: passThrough },
  ChatErrorBoundary: { ChatErrorBoundary: passThrough },
}, { window: fakeWindow, URLSearchParams });

// The app as AppContainer runs it: one active area; an area switch carries the page fields of the target.
async function renderAdminConnections() {
  const switches = [], returns = [];
  fakeWindow.location.search = "?area=admin";
  function App() {
    const [activeArea, setArea] = useState("admin");
    return createElement(AppContainerView, {
      activeArea,
      // The params object comes from the vm realm of the loaded modules; compare it as plain data.
      setActiveArea: (area, params) => {
        switches.push(JSON.parse(JSON.stringify({ area, params })));
        fakeWindow.location.search = `?${new URLSearchParams({ area, ...(params ?? {}) })}`;
        setArea(area);
      },
      loading: false,
      chatState: { currentUser: { id: "u1", roles: ["admin"] }, projects: [{ id: "p1", name: "Test" }], selectedProjectId: "p1" },
      activeBranding: { app_name: "Octryx" },
      adminPanelInitialTab: "adminConnections",
      openSettingsTab(tab) { returns.push(tab); },
      loadState: async () => {},
    });
  }
  let view;
  await act(async () => { view = TestRenderer.create(createElement(App)); });
  // The Admin panel is lazy; let it resolve.
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  return { view, switches, returns };
}

const segment = (view, label) => view.root.findAll((node) => node.props?.role === "tab" && node.type === "button")
  .find((node) => text(node) === label);
const byTestId = (view, id) => view.root.findAll((node) => node.props?.["data-testid"] === id && typeof node.type === "string");

test("Admin › Connections › Repositories leaves the Connections list and opens the repositories page", async () => {
  const { view, switches, returns } = await renderAdminConnections();
  assert.equal(byTestId(view, "connections-page").length, 1, "Admin › Connections shows the Connections list");
  const views = view.root.findAll((node) => node.props?.role === "tablist").find((node) => node.props["aria-label"] === "Connections views");
  assert.ok(views, "the Connections views are segments");
  const repositories = segment(view, "Repositories");
  assert.ok(repositories, "Repositories is a segment of Admin › Connections");

  await act(async () => repositories.props.onClick());

  assert.deepEqual(switches, [{ area: "coding", params: { coding_view: "repositories", return_to: "admin-connections" } }]);
  assert.equal(byTestId(view, "connections-page").length, 0, "the Connections list is gone");
  assert.equal(byTestId(view, "coding-area").length, 1, "Coding is on screen");
  assert.equal(byTestId(view, "admin-return-link").length, 1, "with the way back to Admin › Connections");
  // `coding_view=repositories` opens Work › Repositories for those who manage work (review: a page of the Work
  // menu); a member gets the repository list alone.
  assert.equal(codingWorkspaceView(true), "work");
  assert.equal(codingWorkspaceView(false), "repositories");
  act(() => view.unmount());
});

test("Admin › Connections › Jira write-back opens Work's write-back page the same way", async () => {
  const { view, switches, returns } = await renderAdminConnections();
  await act(async () => segment(view, "Jira write-back").props.onClick());
  assert.deepEqual(switches, [{ area: "work", params: { work_view: "writeback", return_to: "admin-connections" } }]);
  assert.equal(byTestId(view, "connections-page").length, 0);
  assert.equal(byTestId(view, "work-area").length, 1);
  // The page Admin opened says how to get back, and gets there.
  const back = byTestId(view, "admin-return-link");
  assert.equal(back.length, 1, "a link back to Admin › Connections above the page");
  assert.equal(text(back[0]), "← Admin › Connections");
  act(() => back[0].props.onClick());
  assert.deepEqual(returns, ["adminConnections"]);
  act(() => view.unmount());
});

// The page the segment opens, empty: one line, its one action leads to Knowledge › Sources with Add source open.
test("the empty repository list links to Knowledge › Sources › Add source", async () => {
  const fetch = async () => ({ ok: true, status: 200, json: async () => ({ items: [], may_author: false }) });
  const globals = { fetch, window: { location: { search: "" } }, URL, URLSearchParams, AbortController, Error };
  const { RepositoryList } = load("chat/coding/repository/RepositoryList.tsx", {}, globals);
  let view;
  await act(async () => { view = TestRenderer.create(createElement(RepositoryList, { workspaceId: "ws-1", workspaceControl: null })); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  const [line] = byTestId(view, "repository-list-empty");
  assert.ok(line, "one empty line");
  const link = line.findAll((node) => node.type === "a")[0];
  // A reader (no Workspace author): the Knowledge source is the one way; "Add a repository for runs" is an author's.
  assert.equal(text(link), "Add a Knowledge source");
  // It opens Add source on a git repository "From a connection" (Bitbucket, GitHub, ...).
  assert.equal(link.props.href,
    "/chat?area=knowledge&tab=workspaceKnowledge&workspace_id=ws-1&source=new&kind=git_repository&from=connection");
  assert.match(text(line), /^No repository connected yet\./);
  act(() => view.unmount());
});

// Alpha (fresh-install test: no UI path to a repository a run can use): an author's empty page offers
// "Add a repository for runs", which opens its side panel with the Workspace's code connections.
test("an author's empty repository list adds a repository for runs in a side panel", async () => {
  const calls = [];
  const fetch = async (url) => {
    calls.push(String(url));
    const body = String(url).endsWith("/repositories/connections")
      ? { items: [{ id: "c-1", name: "GitHub (demo)", connector: "github", bound_scopes: [] }] }
      : { items: [], may_author: true, permissions: { may_author: true } };
    return { ok: true, status: 200, json: async () => body };
  };
  const globals = { fetch, window: { location: { search: "" } }, URL, URLSearchParams, AbortController, Error,
    document: { activeElement: null, addEventListener() {}, removeEventListener() {} } };
  const { RepositoryList } = load("chat/coding/repository/RepositoryList.tsx", {}, globals);
  let view;
  await act(async () => { view = TestRenderer.create(createElement(RepositoryList, { workspaceId: "ws-author", workspaceControl: null })); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  const [line] = byTestId(view, "repository-list-empty");
  const action = line.findAll((node) => node.type === "button")[0];
  assert.equal(text(action), "Add a repository for runs");
  await act(async () => { action.props.onClick(); await new Promise((resolve) => setTimeout(resolve, 0)); });
  assert.equal(byTestId(view, "run-repository-panel").length, 1, "the side panel opens");
  assert.ok(calls.some((url) => url.endsWith("/api/v1/workspaces/ws-author/repositories/connections")));
  act(() => view.unmount());
});
