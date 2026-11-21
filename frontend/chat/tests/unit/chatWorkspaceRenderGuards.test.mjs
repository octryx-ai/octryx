// Render guards for chat components that no other unit test renders: each one is rendered with representative
// props through a transpile + vm loader and its key text and structure are pinned, so splitting a component into
// smaller parts keeps the rendered output.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = fileURLToPath(new URL("../../src/", import.meta.url));

const windowStub = () => ({
  location: { origin: "http://localhost", href: "http://localhost/chat", assign: () => {} },
  localStorage: { getItem: () => null, setItem: () => {} },
  addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => true,
  matchMedia: () => ({ matches: false, addEventListener: () => {}, removeEventListener: () => {} }),
  innerWidth: 1280,
});

// Loads a source file; relative imports load further source files unless a stub's key ends the import path.
function load(relative, { stubs = {}, globals = {} } = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Intl, Promise,
      encodeURIComponent, setTimeout, clearTimeout, requestAnimationFrame: () => 0,
      window: windowStub(), document: { getElementById: () => null }, ...globals,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const key = Object.keys(stubs).find((suffix) => name.endsWith(suffix));
          if (key) return stubs[key];
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
          throw new Error(`unexpected import ${name} from ${file}`);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

const texts = (node) => node.findAll((n) => typeof n.type === "string").map((n) => n.children.filter((c) => typeof c === "string").join("")).join("|");
const buttons = (view) => view.root.findAllByType("button").map((b) => b.children.flat().filter((c) => typeof c === "string").join(""));
const probe = (testId) => (props) => createElement("div", { "data-testid": testId, "data-props": Object.keys(props).sort().join(",") });

test("ApprovalBubble: a pending command shows title, meta, actions, the preview and the reason", () => {
  const { ApprovalBubble } = load("chat/ApprovalBubble.tsx", { stubs: { "/ApprovalPreview": { ApprovalPreview: probe("approval-preview") } } });
  const approval = {
    id: "ap-1", status: "pending", action: "Run tests", reason: "Command needs approval\nanalyzers: shell",
    createdAt: "2026-01-02T10:00:00Z", toolName: "run_command",
    changePreview: { toolName: "run_command", requestFingerprint: "abcdef0123456789abcdef", preview: { summary: "Run the suite", command: "npm test", cwd: "/repo" } },
  };
  const decisions = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(ApprovalBubble, { approval, onDecision: (_a, kind) => decisions.push(kind) })); });
  assert.equal(view.root.findAllByProps({ className: "message-row message-row--approval" }).length, 1);
  assert.ok(view.root.findByProps({ "data-testid": "approval-title" }));
  assert.ok(buttons(view).length >= 2, buttons(view).join(","));
  assert.ok(view.root.findByProps({ "data-testid": "approval-preview" }));
  const all = texts(view.root);
  assert.match(all, /Inspect governed change/);
  assert.match(all, /Why this needs approval/);
  const snapshot = JSON.stringify(view.toJSON());
  act(() => view.root.findAllByType("button").at(-1).props.onClick());
  assert.equal(decisions.length, 1);
  act(() => view.update(createElement(ApprovalBubble, { approval, onDecision: () => {} })));
  assert.equal(JSON.stringify(view.toJSON()), snapshot);
  act(() => view.unmount());
});

test("ApprovalBubble: a rerun in progress stays busy when the card switches type and back", async () => {
  const { ApprovalBubble } = load("chat/ApprovalBubble.tsx", { stubs: { "/ApprovalPreview": { ApprovalPreview: probe("approval-preview") } } });
  const inline = {
    id: "ap-2", status: "pending", action: "Run tests", reason: "Command needs approval", createdAt: "2026-01-02T10:00:00Z",
    changePreview: { toolName: "run_command", preview: { summary: "Run the suite", command: "npm test" } },
  };
  const connectorWrite = { ...inline, changePreview: { toolName: "jira_create_issue", preview: { connection: "Jira", details: ["connector: jira", "Project: PRJ"] } } };
  let finish;
  const onRetryFromApproval = () => new Promise((resolve) => { finish = resolve; });
  const props = (approval) => ({ approval, onDecision: () => {}, onRetryFromApproval, retryPrompt: "again" });
  let view;
  act(() => { view = TestRenderer.create(createElement(ApprovalBubble, props(inline))); });
  const retry = () => view.root.findAllByType("button").find((b) => /Retry from here|Rerunning/.test(b.children.flat().join("")));
  await act(async () => { retry().props.onClick(); });
  assert.ok(buttons(view).includes("Rerunning…"), buttons(view).join(","));
  act(() => view.update(createElement(ApprovalBubble, props(connectorWrite))));
  assert.ok(!buttons(view).includes("Rerunning…"), "the connector write card has no rerun");
  act(() => view.update(createElement(ApprovalBubble, props(inline))));
  assert.ok(buttons(view).includes("Rerunning…"), "the rerun is still running after the switch back");
  await act(async () => { finish(); });
  assert.ok(buttons(view).includes("Retry from here"), buttons(view).join(","));
  act(() => view.unmount());
});

function fetchStub(routes) {
  const calls = [];
  const fetch = async (url) => {
    calls.push(String(url));
    const route = routes.find(([match]) => String(url).includes(match));
    const [, status, body] = route ?? ["", 404, ""];
    return { ok: status < 400, status, json: async () => body, text: async () => (typeof body === "string" ? body : JSON.stringify(body)) };
  };
  return { fetch, calls };
}

test("OfficeWorkspace: the rendered preview first, the inspector after a failed preview", async () => {
  const stubs = {
    "/artifactPreviewOfficePanels": { OfficeContentPanel: probe("office-content") },
    "/artifactPreviewOfficeSidecar": { OfficeDetailsSidecar: probe("office-sidecar") },
    "/artifactPreviewOfficeToolbar": { OfficeToolbar: (props) => createElement("div", { "data-testid": "office-toolbar", "data-mode": props.mode, "data-copy": String(props.showToolbarCopy) }, props.modeTitle) },
  };
  const artifact = { name: "plan.docx", path: "docs/plan.docx", kind: "file" };
  const ok = fetchStub([["actions", 200, { actions: [{ id: "a1", label: "Summarize" }] }], ["", 200, "<p>Doc</p>"]]);
  const { OfficeWorkspace } = load("chat/artifactPreviewOfficeWorkspace.tsx", { stubs, globals: { fetch: ok.fetch } });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(OfficeWorkspace, { artifact })); });
  const frame = view.root.findByType("iframe");
  assert.equal(frame.props.srcDoc, "<p>Doc</p>");
  assert.equal(frame.props.sandbox, "allow-scripts");
  assert.equal(view.root.findByProps({ "data-testid": "office-toolbar" }).props["data-mode"], "html");
  assert.equal(view.root.findAllByProps({ "data-testid": "office-sidecar" }).length, 0);
  assert.ok(view.root.findByProps({ className: "artifact-preview__office-layout artifact-preview__office-layout--focus" }));
  assert.equal(ok.calls.length, 2);
  act(() => view.unmount());

  const failing = fetchStub([["actions", 500, {}]]);
  const reloaded = load("chat/artifactPreviewOfficeWorkspace.tsx", { stubs, globals: { fetch: failing.fetch } });
  await act(async () => { view = TestRenderer.create(createElement(reloaded.OfficeWorkspace, { artifact })); });
  assert.match(texts(view.root), /Preview unavailable/);
  const sidecar = view.root.findByProps({ "data-testid": "office-sidecar" });
  assert.match(sidecar.props["data-props"], /actionsError/);
  assert.ok(view.root.findByProps({ className: "artifact-preview__office-layout" }));
  act(() => view.unmount());
});

test("DiagramViewer: an image first for a known diagram, the embed without one", () => {
  const { DiagramViewer } = load("chat/DiagramViewer.tsx");
  let view;
  act(() => { view = TestRenderer.create(createElement(DiagramViewer, { xml: "<mxfile/>", title: "Flow", diagramId: "d-1" })); });
  assert.deepEqual(buttons(view), ["XML", "Edit inline", "Open in Editor ↗"]);
  assert.match(view.root.findByType("img").props.src, /diagram%3A%2F%2Fd-1/);
  assert.match(texts(view.root), /Diagram preview\|.*Flow\|ID d-1/);
  act(() => view.root.findAllByType("button")[0].props.onClick());
  assert.equal(view.root.findByType("pre").children.join(""), "<mxfile/>");
  assert.deepEqual(buttons(view), ["Hide XML", "Edit inline", "Open in Editor ↗"]);
  act(() => view.root.findAllByType("button")[1].props.onClick());
  assert.equal(view.root.findAllByType("img").length, 0);
  assert.equal(view.root.findByType("iframe").props.title, "Flow");
  act(() => view.unmount());
  act(() => { view = TestRenderer.create(createElement(DiagramViewer, { xml: "<x/>" })); });
  assert.deepEqual(buttons(view), ["XML", "Open in Editor ↗"]);
  assert.match(texts(view.root), /Loading diagram…/);
  act(() => view.unmount());
});

function startView(overrides = {}) {
  return {
    workflowKey: "wf", projectId: "p1", workflowTitle: "Delivery", summary: "Deliver the change",
    item: { mode: "new", typeLabel: "Story", title: "Add login", description: "Short", longDescription: false, key: null, href: null, id: null },
    jiraProject: null, jiraLabel: "+ Jira MM", notes: ["note one"], steps: ["Plan", "Build"],
    runOn: { options: [{ key: "cloud", label: "Cloud", help: "Runs in the cloud", offline: false }], selected: "cloud" },
    repository: { name: null, id: null, sourceText: null, options: [{ id: "r1", name: "repo" }] },
    outcome: { kind: "none" }, ...overrides,
  };
}

test("WorkflowStartCard: an open start, a refused start and a started run", () => {
  const stubs = {
    "/RunOnSelect": { RunOnSelect: probe("run-on") },
    "/StartModelBudget": { StartModelBudget: probe("model-budget") },
    "/StartRepository": { StartRepository: probe("start-repository") },
  };
  const { WorkflowStartCard } = load("chat/run/WorkflowStartCard.tsx", { stubs });
  const base = { reason: "Because", decided: null, disabled: false, onStart: async () => {}, onSkip: async () => {}, otherOpen: false, onOther: () => {}, picker: null };
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkflowStartCard, { ...base, view: startView() })); });
  assert.equal(view.root.findByProps({ "data-testid": "workflow-start-card" }).props.className, "workflow-start workflow-start--attention");
  assert.deepEqual(buttons(view), ["Don't start", "Other workflow…", "Start"]);
  assert.equal(view.root.findByProps({ "data-testid": "workflow-start-blocked" }).children.join(""), "Choose the repository the run works in");
  assert.equal(view.root.findAllByType("li").length, 3);
  for (const id of ["run-on", "model-budget", "start-repository", "workflow-start-jira"]) assert.ok(view.root.findByProps({ "data-testid": id }), id);
  assert.match(texts(view.root), /Start a workflow\|Deliver the change\|Because/);
  const failed = { kind: "error", reason: "No budget", itemId: "i1", itemKey: "W-1", itemHref: "/w/1", jiraKey: "MM-1", jiraProblem: null };
  act(() => view.update(createElement(WorkflowStartCard, { ...base, decided: "apply", view: startView({ outcome: failed, repository: null }) })));
  assert.deepEqual(buttons(view), ["Don't start", "Other workflow…", "Start again"]);
  assert.match(texts(view.root), /Delivery did not start: No budget/);
  assert.ok(view.root.findByProps({ "data-testid": "workflow-start-jira-key" }));
  const started = { kind: "started", href: "/run/1", runId: "r1", itemId: "i1", itemKey: "W-1", itemHref: null, jiraKey: null, jiraProblem: "denied" };
  act(() => view.update(createElement(WorkflowStartCard, { ...base, decided: "apply", view: startView({ outcome: started }) })));
  assert.equal(buttons(view).length, 0);
  assert.ok(view.root.findByProps({ "data-testid": "workflow-start-open-run" }));
  assert.ok(view.root.findByProps({ "data-testid": "workflow-start-jira-problem" }));
  assert.match(texts(view.root), /Workflow started/);
  act(() => view.unmount());
});

test("WorkspaceSidePanel: files with the navigator, then the changes tab", () => {
  const panelProbe = (testId) => (props) => createElement("div", { "data-testid": testId, "data-count": String(props.fileCount ?? props.displayedFiles?.length ?? props.filteredChanges?.length ?? ""), "data-tab": props.activeTab ?? "" });
  const stubs = {
    "/workspaceSidePanelPanels": { WorkspaceSidePanelHeader: panelProbe("panel-header"), WorkspaceSidePanelControls: panelProbe("panel-controls"), WorkspaceChangesPanel: panelProbe("panel-changes") }, "/WorkspaceSidePanelFilesPanel": { WorkspaceFilesPanel: panelProbe("panel-files") },
    "/WorkspaceSidePanelPreviewPanel": { WorkspaceSidePanelPreviewPanel: probe("preview") },
  };
  const { WorkspaceSidePanel } = load("chat/WorkspaceSidePanel.tsx", { stubs });
  const workspace = {
    rootPath: "/ws", rootLabel: "ws", loadedDirectories: [""],
    files: [{ relativePath: "b.txt", name: "b.txt", kind: "file", parentPath: "" }, { relativePath: "a", name: "a", kind: "directory", parentPath: "" }],
    changes: [{ summary: "Edited b", toolName: "write", requestFingerprint: "f" }],
  };
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkspaceSidePanel, { workspace, onOpenArtifact: () => {} })); });
  assert.equal(view.root.findByProps({ "data-testid": "panel-controls" }).props["data-count"], "2");
  assert.equal(view.root.findByProps({ "data-testid": "panel-files" }).props["data-count"], "2");
  assert.match(texts(view.root), /Navigator\|2 items/);
  assert.equal(view.root.findAllByProps({ "data-testid": "preview" }).length, 0);
  assert.equal(view.root.findAllByProps({ "data-testid": "panel-changes" }).length, 0);
  act(() => view.root.findByProps({ "data-testid": "panel-controls" }).parent.props.onChangeTab("changes"));
  assert.match(texts(view.root), /Changes\|1 item/);
  assert.equal(view.root.findByProps({ "data-testid": "panel-changes" }).props["data-count"], "1");
  act(() => view.unmount());
});

test("CodingSessionStartDialog: the items, the prefilled request and the known repositories", () => {
  const created = [];
  const { CodingSessionStartDialog } = load("chat/coding/CodingSessionStartDialog.tsx", {
    stubs: { "/codingSessionPlanRequest": { createCodingSessionPlan: async () => {} } },
  });
  const item = (id, key) => ({ id, source_key: key, title: `Title ${key}`, source_status: "To Do", assignee: null, work_state: "ready", labels: ["x"], description: "Do it" });
  const props = { open: true, items: [item("i1", "MM-1"), item("i2", "MM-2")], repositoryProfiles: [{ id: "r1", name: "repo-one" }], onClose: () => {}, onCreated: (id) => created.push(id) };
  let view;
  act(() => { view = TestRenderer.create(createElement(CodingSessionStartDialog, props)); });
  assert.equal(view.root.findByProps({ role: "dialog" }).props["aria-labelledby"], "coding-start-title");
  assert.equal(view.root.findByProps({ className: "coding-start__items" }).findAllByType("button").length, 2);
  assert.equal(view.root.findAllByProps({ className: "is-active" }).length, 1);
  assert.equal(view.root.findAllByType("textarea").length, 5);
  assert.ok(view.root.findAllByType("textarea")[0].props.value.length > 0, "the request is prefilled");
  const all = buttons(view);
  assert.ok(all.includes("Close") && all.includes("Cancel") && all.includes("+ repo-one"), all.join(","));
  assert.match(texts(view.root), /Coding · Step 1: change plan/);
  assert.match(texts(view.root), /Rollback plan/);
  act(() => view.update(createElement(CodingSessionStartDialog, { ...props, open: false })));
  assert.equal(view.toJSON(), null);
  act(() => view.unmount());
});
