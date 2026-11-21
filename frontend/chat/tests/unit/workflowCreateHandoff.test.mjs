// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workflowCreateHandoff.test.mjs
//
// One place to create workflows: Workspace settings creates no agent templates; it links to the Flow Builder
// create drawer with the workspace preselected. The link creates nothing, never falls back to Global for an
// unavailable workspace, and is not replayed.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement, useState } from "react";
import TestRenderer from "react-test-renderer";
import * as editorLinks from "../../src/admin/editorLinks.ts";
import * as adminPanelLoad from "../../src/admin/components/adminPanelLoad.ts";
import * as flowBuilderTemplates from "../../src/admin/components/flowBuilder/flowBuilderTemplates.ts";
import * as flowDraftCreation from "../../src/admin/components/flowBuilder/flowDraftCreation.ts";
import * as handoff from "../../src/admin/components/flowBuilder/useFlowCreateHandoff.ts";
import * as loadingState from "../../src/layout/LoadingState.ts";
import { flowBuilderTabSource } from "./flowBuilderTabSource.mjs";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const src = (path) => new URL(`../../src/admin/${path}`, import.meta.url);
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

// Transpiles one .tsx component and runs it with the given module stubs (matched by suffix).
function loadComponent(path, exportName, stubs) {
  return loadModule(path, stubs)[exportName];
}

function loadModule(path, stubs) {
  const source = fs.readFileSync(src(path), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const exports = {};
  vm.runInNewContext(output, {
    exports,
    crypto: globalThis.crypto,
    window: globalThis.window,
    require: (name) => {
      if (name.endsWith(".css")) return {};
      if (name.endsWith("/layout/LoadingState")) return loadingState;
      const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
      return stub ? stub[1] : require(name);
    },
  });
  return exports;
}

const workspaces = [
  { id: "ws-1", name: "Petclinic", is_active: true },
  { id: "ws-off", name: "Archived", is_active: false },
];

test("the workspace link opens Flow Builder's create drawer for that workspace", () => {
  const url = new URL(editorLinks.flowBuilderCreateHref("ws 1"), "http://x");
  assert.equal(url.pathname, "/chat");
  assert.equal(url.searchParams.get("area"), "workflows");
  assert.equal(url.searchParams.get("tab"), "workflowList");
  assert.equal(url.searchParams.get(editorLinks.WORKSPACE_ID_PARAM), "ws 1");
  assert.equal(url.searchParams.get(editorLinks.NEW_FLOW_PARAM), "1");
});

test("a create request preselects only an available, active workspace and never falls back to Global", () => {
  const { resolveFlowCreateRequest, UNAVAILABLE_WORKSPACE_NOTICE } = handoff;
  assert.equal(resolveFlowCreateRequest("?area=workflows&tab=workflowList&workspace_id=ws-1", workspaces), null);
  assert.deepEqual(resolveFlowCreateRequest("?new_flow=1&workspace_id=ws-1", workspaces), { scope: "ws-1", notice: null });
  assert.deepEqual(resolveFlowCreateRequest("?new_flow=1", workspaces), { scope: "", notice: null });
  for (const search of ["?new_flow=1&workspace_id=ws-missing", "?new_flow=1&workspace_id=ws-off"]) {
    const request = resolveFlowCreateRequest(search, workspaces);
    assert.deepEqual(request, { scope: "", notice: UNAVAILABLE_WORKSPACE_NOTICE });
    assert.notEqual(request.scope, flowDraftCreation.GLOBAL_WORKFLOW_SCOPE);
  }
  // Workspaces without an explicit inactive flag (the chat-state list) count as available.
  assert.deepEqual(resolveFlowCreateRequest("?new_flow=1&workspace_id=ws-2", [{ id: "ws-2", name: "X" }]), { scope: "ws-2", notice: null });
});

test("settling removes only the create request from the address; the workspace context stays", () => {
  const { urlWithoutCreateRequest } = handoff;
  assert.equal(
    urlWithoutCreateRequest("https://octryx.example/chat?area=workflows&tab=workflowList&workspace_id=ws-1&new_flow=1#top"),
    "/chat?area=workflows&tab=workflowList&workspace_id=ws-1#top",
  );
  assert.equal(urlWithoutCreateRequest("https://octryx.example/chat?tab=workflowList"), null);
  assert.equal(urlWithoutCreateRequest("not a url"), null);
});

const LINK = "https://octryx.example/chat?area=workflows&tab=workflowList&workspace_id=ws-1&new_flow=1";

// A browser address the hook can read and replace.
function fakeWindow(href) {
  const win = { location: {}, history: { state: null } };
  const go = (next) => {
    const url = new URL(next, win.location.href || undefined);
    win.location.href = url.href;
    win.location.search = url.search;
  };
  win.history.replaceState = (state, _title, url) => { win.history.state = state; go(url); };
  go(href);
  return win;
}

// The same glue as AdminFlowBuilderTab: a request selects the workspace filter and opens the
// existing drawer; Cancel and a created draft settle the request.
function makeFlowBuilderProbe(Drawer, readJson) {
  return function FlowBuilderProbe({ projects }) {
    const [request, setRequest] = useState(null);
    const [open, setOpen] = useState(false);
    const [projectId, setProjectId] = useState("");
    const settle = handoff.useFlowCreateHandoff(projects, (next) => {
      if (next.scope) setProjectId(next.scope);
      setRequest(next);
      setOpen(true);
    });
    return createElement("section", { "data-project": projectId },
      open
        ? createElement(Drawer, {
          projects, readJson, initialScope: request?.scope, scopeNotice: request?.notice,
          onClose: () => { settle(); setOpen(false); setRequest(null); },
          onCreated: () => { settle(); setRequest(null); setOpen(false); },
        })
        : null);
  };
}

const scopeValue = (root) => root.findAll((node) => node.type === "select" && node.props.required)[0]?.props.value;
const drawerOpen = (root) => root.findAll((node) => node.type === "form").length === 1;

test("the hook reads the open request on every mount and leaves the address until it is settled", () => {
  globalThis.window = fakeWindow(LINK);
  const requests = [];
  let settle;
  function Probe({ list }) {
    settle = handoff.useFlowCreateHandoff(list, (request) => requests.push(request));
    return null;
  }
  let view;
  act(() => { view = TestRenderer.create(createElement(Probe, { list: workspaces })); });
  act(() => { view.update(createElement(Probe, { list: [...workspaces] })); });
  assert.deepEqual(requests, [{ scope: "ws-1", notice: null }], "a re-render does not repeat it");
  assert.equal(window.location.href, LINK, "mounting never consumes the request");
  act(() => view.unmount());
  act(() => { view = TestRenderer.create(createElement(Probe, { list: workspaces })); });
  assert.equal(requests.length, 2, "a remount before the user settled reads it again");
  act(() => settle());
  assert.equal(window.location.href, "https://octryx.example/chat?area=workflows&tab=workflowList&workspace_id=ws-1");
  act(() => view.unmount());
  act(() => { view = TestRenderer.create(createElement(Probe, { list: workspaces })); });
  assert.equal(requests.length, 2, "after settling, a remount or reload does not reopen it");
  act(() => view.unmount());
  delete globalThis.window;
});

const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

// The real admin panel switch: every panel mount runs loadTab, which shows "Loading…" in place of
// the panel and then mounts it again (AdminPanelContent `if (loadingTab)`).
function loadAdminPanelContent(Probe) {
  const LoadBoundary = loadComponent("components/AdminPanelLoadBoundary.tsx", "AdminPanelLoadBoundary", { "/adminPanelLoad": adminPanelLoad });
  const stubs = {
    "/AdminPanelLoadBoundary": { AdminPanelLoadBoundary: LoadBoundary },
    "/adminPanelLoad": adminPanelLoad,
    "/flowBuilder/AdminFlowBuilderTab": { AdminFlowBuilderTab: Probe },
    // The Workflows page renders the flow builder for a create request (`tab=workflowList`).
    "/agentsWorkflows/workflows/WorkflowsPage": { WorkflowsPage: (props) => createElement(Probe, props) },
  };
  return loadComponent("components/AdminPanelContent.tsx", "AdminPanelContent", {
    ...stubs,
    "/adminPanelLazyPages": loadModule("components/adminPanelLazyPages.ts", stubs),
  });
}

test("the create drawer survives the admin loader's unmount and remount until Cancel settles it", async () => {
  globalThis.window = fakeWindow(LINK);
  const calls = [];
  const Probe = makeFlowBuilderProbe(loadDrawer(), async (url, init) => { calls.push([url, init]); return { id: "f-1" }; });
  const Content = loadAdminPanelContent(Probe);
  const panel = (loadingTab) => createElement(Content, { loadingTab, tabError: null, tab: "workflowList", projects: workspaces, readJson: async () => ({}) });
  let view;
  act(() => { view = TestRenderer.create(panel(false)); });
  await flush();
  assert.equal(drawerOpen(view.root), true, "the first mount opens the drawer");
  act(() => view.update(panel(true)));
  assert.equal(drawerOpen(view.root), false);
  assert.match(text(view.root), /Loading this page…/, "the loader replaced the panel");
  act(() => view.update(panel(false)));
  await flush();
  assert.equal(drawerOpen(view.root), true, "the remounted panel opens the drawer again");
  assert.equal(scopeValue(view.root), "ws-1");
  assert.equal(view.root.findByType("section").props["data-project"], "ws-1", "the workspace filter follows the request");
  assert.equal(window.location.href, LINK);
  assert.equal(calls.length, 0, "nothing is created by mounting");

  act(() => buttons(view.root, "Cancel")[0].props.onClick());
  assert.equal(drawerOpen(view.root), false);
  assert.equal(window.location.href, "https://octryx.example/chat?area=workflows&tab=workflowList&workspace_id=ws-1");
  act(() => view.update(panel(true)));
  act(() => view.update(panel(false)));
  await flush();
  assert.equal(drawerOpen(view.root), false, "a remount after Cancel does not reopen it");
  act(() => view.unmount());
  act(() => { view = TestRenderer.create(panel(false)); });
  await flush();
  assert.equal(drawerOpen(view.root), false, "a reload after Cancel does not reopen it");
  assert.equal(calls.length, 0);
  act(() => view.unmount());
  delete globalThis.window;
});

test("a created draft settles the request, so a later remount does not offer it again", async () => {
  globalThis.window = fakeWindow(LINK);
  const calls = [];
  const Probe = makeFlowBuilderProbe(loadDrawer(), async (url, init) => { calls.push([url, init]); return { id: "f-1" }; });
  const Content = loadAdminPanelContent(Probe);
  const panel = (loadingTab) => createElement(Content, { loadingTab, tabError: null, tab: "workflowList", projects: workspaces, readJson: async () => ({}) });
  let view;
  act(() => { view = TestRenderer.create(panel(false)); });
  act(() => view.update(panel(true)));
  act(() => view.update(panel(false)));
  await flush();
  act(() => view.root.findByType("input").props.onChange({ target: { value: "Triage" } }));
  await act(async () => { view.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
  assert.equal(calls.length, 1);
  assert.equal(JSON.parse(calls[0][1].body).project_id, "ws-1");
  assert.equal(window.location.href, "https://octryx.example/chat?area=workflows&tab=workflowList&workspace_id=ws-1");
  act(() => view.update(panel(true)));
  act(() => view.update(panel(false)));
  await flush();
  assert.equal(drawerOpen(view.root), false);
  assert.equal(calls.length, 1);
  act(() => view.unmount());
  delete globalThis.window;
});

test("an empty workspace list opens the drawer as unavailable: no wait, no Global, Create disabled", () => {
  // A user with no visible workspace, or Flow Builder after a failed chat bootstrap.
  assert.deepEqual(handoff.resolveFlowCreateRequest("?new_flow=1&workspace_id=ws-1", []), { scope: "", notice: handoff.UNAVAILABLE_WORKSPACE_NOTICE });
  globalThis.window = fakeWindow(LINK);
  const calls = [];
  const Probe = makeFlowBuilderProbe(loadDrawer(), async (url, init) => { calls.push([url, init]); return {}; });
  let view;
  act(() => { view = TestRenderer.create(createElement(Probe, { projects: [] })); });
  assert.equal(drawerOpen(view.root), true, "the drawer opens right away instead of waiting");
  assert.equal(scopeValue(view.root), "", "nothing is preselected, not even Global");
  assert.equal(text(view.root.findByProps({ role: "status" })), handoff.UNAVAILABLE_WORKSPACE_NOTICE);
  assert.match(handoff.UNAVAILABLE_WORKSPACE_NOTICE, /cannot currently use/);
  act(() => view.root.findByType("input").props.onChange({ target: { value: "Triage" } }));
  assert.equal(view.root.find((node) => node.type === "button" && node.props.type === "submit").props.disabled, true, "Create stays disabled until a scope is chosen");
  act(() => buttons(view.root, "Cancel")[0].props.onClick());
  assert.equal(window.location.href, "https://octryx.example/chat?area=workflows&tab=workflowList&workspace_id=ws-1");
  assert.equal(calls.length, 0);
  act(() => view.unmount());
  delete globalThis.window;
});

function loadDrawer() {
  const GovernedDrawer = ({ title, footer, children }) => createElement("aside", { "data-title": title }, children, footer);
  return loadComponent("components/flowBuilder/FlowDraftCreateDrawer.tsx", "FlowDraftCreateDrawer", {
    "/GovernedDrawer": { GovernedDrawer },
    "/flowBuilderTemplates": flowBuilderTemplates,
    "/flowDraftCreation": flowDraftCreation,
  });
}

test("the drawer preselects the workspace and creates only on the explicit Create confirmation", async () => {
  const Drawer = loadDrawer();
  const calls = [];
  const readJson = async (url, init) => { calls.push([url, init]); return { id: "f-1" }; };
  const created = [];
  let view;
  act(() => {
    view = TestRenderer.create(createElement(Drawer, {
      projects: workspaces.filter((item) => item.is_active), readJson, onClose: () => {}, onCreated: (flow) => created.push(flow), initialScope: "ws-1",
    }));
  });
  const [scopeSelect] = view.root.findAll((node) => node.type === "select" && node.props.required);
  assert.equal(scopeSelect.props.value, "ws-1");
  assert.equal(calls.length, 0, "opening the drawer must not create anything");
  const submit = view.root.find((node) => node.type === "button" && node.props.type === "submit");
  assert.equal(submit.props.disabled, true, "a name is still required");

  act(() => view.root.findByType("input").props.onChange({ target: { value: "Triage" } }));
  assert.equal(calls.length, 0);
  await act(async () => { view.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
  assert.equal(calls.length, 1);
  assert.equal(calls[0][0], "/api/v1/flows");
  assert.equal(calls[0][1].method, "POST");
  assert.equal(JSON.parse(calls[0][1].body).project_id, "ws-1");
  assert.equal(created.length, 1);
  act(() => view.unmount());
});

test("an unavailable workspace opens the drawer with no workspace chosen and says why", () => {
  const Drawer = loadDrawer();
  let view;
  act(() => {
    view = TestRenderer.create(createElement(Drawer, {
      projects: [], readJson: async () => ({}), onClose: () => {}, onCreated: () => {}, initialScope: "", scopeNotice: handoff.UNAVAILABLE_WORKSPACE_NOTICE,
    }));
  });
  const [scopeSelect] = view.root.findAll((node) => node.type === "select" && node.props.required);
  assert.equal(scopeSelect.props.value, "");
  assert.equal(text(view.root.findByProps({ role: "status" })), handoff.UNAVAILABLE_WORKSPACE_NOTICE);
  assert.equal(view.root.find((node) => node.type === "button" && node.props.type === "submit").props.disabled, true);
  act(() => view.unmount());
});

const buttons = (root, label) => root.findAll((node) => node.type === "button" && text(node) === label);

test("Flow Builder wires the handoff through the focused hook into the existing create drawer", () => {
  const source = flowBuilderTabSource();
  assert.match(source, /const settleCreateRequest = useFlowCreateHandoff\(projects, \(request\) => \{/);
  // Only an explicit Cancel or a created draft settles the request.
  // Embedded in the Workflows page, closing the drawer without an open flow hands back to the page.
  assert.match(source, /onClose=\{\(\) => \{ settleCreateRequest\(\); setCreateDrawerOpen\(false\); setCreateRequest\(null\); if \(!editorOpen\) onExit\(\); \}\}/);
  assert.match(source, /onCreated=\{\(flow\) => \{ settleCreateRequest\(\); setCreateRequest\(null\); void openCreatedDraft\(flow\); \}\}/);
  assert.equal(source.match(/settleCreateRequest\(\)/g).length, 2, "nothing else consumes the request");
  assert.match(source, /initialScope=\{createRequest\?\.scope\} scopeNotice=\{createRequest\?\.notice\}/);
  // A manual "New workflow" starts on the Workflows page; the builder has no library of its own.
  assert.doesNotMatch(source, /onNewDraft=/);
  assert.doesNotMatch(source, /new_flow|NEW_FLOW_PARAM/, "URL handling stays in the hook");
});
