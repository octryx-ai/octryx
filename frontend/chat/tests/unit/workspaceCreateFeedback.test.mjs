// Creating a Workspace gives feedback. The drawer stays open and busy until the list shows
// the new Workspace, then a confirmation names it, offers its settings, and its row is marked. A failure keeps the
// drawer open with the error, so nobody creates a duplicate by clicking again.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const text = (node) => (node === null ? "" : typeof node === "string" ? node : node.children.map(text).join(""));

const seen = { drawer: null, summary: null };
// The confirm hook is its own unit (useConfirmAction); here it records what the tab asks for.
const asked = [];
// Settings requests the tab makes (C7: Set class asks for Rules with the classification first).
const requested = [];
const confirmStub = { ask: (request) => asked.push(request), dialog: null, notice: null };
const Drawer = (props) => { seen.drawer = props; return createElement("div", { "data-testid": "drawer" }, props.creating ? "Creating..." : "Create workspace"); };
const Summary = (props) => { seen.summary = props; return createElement("div", null, `rows:${(props.adminProjects || []).length}`); };
const Panel = (props) => { seen.panel = props; return createElement("div", { "data-testid": "workspace-panel" }, props.project.name); };

function load() {
  const exports = {};
  const source = fs.readFileSync(new URL("../../src/admin/components/AdminProjectsTab.tsx", import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports, Error, window: { confirm: () => true },
    require: (name) => {
      if (name.endsWith("/AdminProjectsSummarySection")) return { AdminProjectsSummarySection: Summary };
      if (name.endsWith("/WorkspaceCreateDrawer")) return { WorkspaceCreateDrawer: Drawer };
      if (name.endsWith("/WorkspaceSettingsPage")) return { WorkspaceSettingsPage: () => null };
      if (name.endsWith("/WorkspaceSidePanel")) return { WorkspaceSidePanel: Panel };
      if (name.endsWith("/workspaceSettingsLink")) {
        return { pendingWorkspaceSettings: () => null, requestWorkspaceSettings: (...args) => requested.push(args), takeUrlWorkspaceSection: () => {} };
      }
      if (name.endsWith("/useWorkspaceClasses")) return { useWorkspaceClasses: () => ({ "p-rs": { level: null, source: "unset" } }) };
      if (name.endsWith("/confirm/useConfirmAction")) return { useConfirmAction: () => confirmStub };
      if (name.endsWith("/useWorkspaceProblemCounts")) return { useWorkspaceProblemCounts: () => null };
      return require(name);
    },
  });
  return exports;
}

function deferred() {
  let resolve; let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function mount(readJson, opened = []) {
  const { AdminProjectsTab } = load();
  let projects = [{ id: "p-rs", name: "Acme Orders" }];
  const ctx = {
    get adminProjects() { return projects; },
    setAdminProjects: (next) => { projects = next; },
    readJson, handleOpenProjectQualityForm: (project) => opened.push(project.id),
  };
  let view;
  act(() => { view = TestRenderer.create(createElement(AdminProjectsTab, { ctx })); });
  return { view, ctx, rerender: () => act(() => view.update(createElement(AdminProjectsTab, { ctx }))) };
}

const submit = () => seen.drawer.onSubmit({ preventDefault() {} });

test("busy until the list shows the new Workspace, then confirmed, marked and one click from its page", async () => {
  const post = deferred();
  const list = deferred();
  const readJson = (url, init) => (init?.method === "POST" ? post.promise : list.promise);
  const opened = [];
  const { view, rerender } = mount(readJson, opened);
  act(() => seen.summary.onCreateWorkspace());
  act(() => seen.drawer.setName("ux-first-run"));
  let done;
  act(() => { done = submit(); });
  assert.equal(seen.drawer.creating, true);
  await act(async () => { post.resolve({ id: "p-new", name: "ux-first-run" }); });
  assert.equal(seen.drawer.creating, true, "still busy while the list reloads");
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "workspace-created").length, 0);
  await act(async () => { list.resolve([{ id: "p-rs", name: "Acme Orders" }, { id: "p-new", name: "ux-first-run" }]); await done; });
  rerender();
  const note = view.root.find((node) => node.props["data-testid"] === "workspace-created");
  assert.match(text(note), /Workspace ux-first-run created\.Open the workspace/);
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "drawer").length, 0, "the drawer closed");
  assert.equal(seen.summary.highlightedProjectId, "p-new");
  // "Open the workspace" opens its side panel; "Open settings" there opens the full settings.
  act(() => note.findByType("button").props.onClick());
  assert.deepEqual(opened, []);
  assert.equal(seen.panel.project.id, "p-new");
  act(() => seen.panel.onOpenSettings());
  assert.deepEqual(opened, ["p-new"]);
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "workspace-panel").length, 0, "the panel closed");
  act(() => view.unmount());
});

test("a row opens the Workspace's side panel, not a page; ✕ closes it", () => {
  const opened = [];
  const { view } = mount(() => Promise.resolve([]), opened);
  act(() => seen.summary.handleOpenProjectQualityForm({ id: "p-rs", name: "Acme Orders" }));
  assert.equal(seen.panel.project.id, "p-rs");
  assert.equal(seen.summary.highlightedProjectId, "p-rs", "its row is selected");
  assert.deepEqual(opened, []);
  act(() => seen.panel.onClose());
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "workspace-panel").length, 0);
  act(() => view.unmount());
});

test("a failed create keeps the drawer open with the error and marks nothing", async () => {
  const readJson = (url, init) => (init?.method === "POST" ? Promise.reject(new Error("A workspace with this name exists.")) : Promise.resolve([]));
  const { view } = mount(readJson);
  act(() => seen.summary.onCreateWorkspace());
  act(() => seen.drawer.setName("Acme Orders"));
  await act(async () => { await submit(); });
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "drawer").length, 1);
  assert.equal(seen.drawer.error, "A workspace with this name exists.");
  assert.equal(seen.summary.highlightedProjectId, null);
  act(() => view.unmount());
});

test("delete and archive ask in the app, naming the Workspace; the confirmed action calls the server", async () => {
  const calls = [];
  const readJson = (url, init) => { calls.push([init?.method ?? "GET", url]); return Promise.resolve([]); };
  const { view } = mount(readJson);
  asked.length = 0;
  act(() => seen.summary.onDeleteProject({ id: "p-rs", name: "Acme Orders" }));
  act(() => seen.summary.onArchiveProject({ id: "p-rs", name: "Acme Orders" }));
  assert.deepEqual(asked.map((request) => [request.title, request.confirmLabel, request.done]), [
    ["Delete Workspace Acme Orders?", "Delete Acme Orders", "Workspace Acme Orders deleted."],
    ["Archive Workspace Acme Orders?", "Archive Acme Orders", "Workspace Acme Orders archived."],
  ]);
  assert.equal(calls.length, 0, "nothing happens before the confirmation");
  await act(async () => { await asked[0].run(""); });
  assert.deepEqual(calls.slice(0, 2), [["DELETE", "/api/v1/projects/p-rs"], ["GET", "/admin/chat/api/panel/projects"]]);
  act(() => view.unmount());
});

test("no browser confirm or alert is left in the destructive actions of this slice", () => {
  for (const file of ["admin/components/AdminProjectsTab.tsx", "chat/devices/AdminDevicesList.tsx", "admin/components/AdminSchedulersTab.tsx",
    "admin/components/scheduler/SchedulerFormPanel.tsx", "admin/components/scheduler/SchedulerDetailPanel.tsx",
    "admin/components/scheduler/schedulerRowWords.tsx",
    "admin/hooks/useAdminTaskSchedulerActions.ts", "admin/components/AdminOutboundWebhooksSection.tsx", "admin/components/AdminOutboundWebhookTable.tsx"]) {
    const source = fs.readFileSync(new URL(`../../src/${file}`, import.meta.url), "utf8");
    assert.doesNotMatch(source, /\b(window\.)?(confirm|alert)\(/, file);
  }
});

test("The list gets each Workspace's class; Set class opens its settings at the classification", () => {
  const opened = [];
  const { view } = mount(async () => [], opened);
  assert.deepEqual(seen.summary.workspaceClasses, { "p-rs": { level: null, source: "unset" } });
  act(() => seen.summary.onOpenClassification({ id: "p-rs", name: "Acme Orders" }));
  assert.deepEqual(requested.at(-1), ["p-rs", "rules", "classification"]);
  assert.deepEqual(opened, ["p-rs"]);
  act(() => view.unmount());
});
