// Render guards for phone components (run page, new chat sheet, phone app and tab screen): key text and structure
// stay the same when the components are split into smaller parts. Heavy children and network modules are stubbed by
// module name.
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
const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));
const noop = () => {};

// Loads a source file; relative imports resolve to a stub (by file name) or to the real .tsx/.ts file.
function load(relative, stubs = {}, globals = {}) {
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
      Math, JSON, Array, String, Boolean, Set, Map, RegExp, encodeURIComponent, setTimeout, clearTimeout,
      window: { localStorage: { getItem: () => null, setItem() {} }, setTimeout, clearTimeout, open() {} },
      document: { hidden: false, addEventListener() {}, removeEventListener() {} },
      ...globals,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          if (stubs[path.basename(base)]) return stubs[path.basename(base)];
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

const box = (testid) => (props) => createElement("div", { "data-testid": testid }, props.children ?? null);
const icon = (props) => createElement("i", { "data-icon": props.name ?? "" });
const flush = () => act(async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); });

async function render(component, props) {
  let view;
  await act(async () => { view = TestRenderer.create(createElement(component, props)); });
  await flush();
  return view;
}

const RUN = {
  id: "r1", title: "Add login", status: "running", updated_at: "2026-11-20T10:00:00Z", project_id: "p1",
  branch: "feat/login", work_item: { id: "w1", key: "PET-7", title: "Add login", state: "in_progress" },
  task_list: [{ id: "1", text: "Write the test", done: true }, { id: "2", text: "Make it pass" }],
  nodes: [{ id: "n1", title: "Plan", kind: "agent", status: "completed" }, { id: "n2", title: "Build", kind: "agent", status: "running" }],
  sessions: [{ id: "s1", role: "main" }],
};

function runPageStubs(run) {
  return {
    mobileApi: { loadRun: async () => ({ run }) },
    pullToRefresh: { useRefreshEvent: noop },
    DecisionCard: { DecisionCard: box("decision-card") },
    SpecStudioLink: { SpecStudioLink: box("studio-link") },
    OpenFindings: { OpenFindings: box("open-findings") },
    icons: { Icon: icon },
    PageHeader: { DetailHeader: (p) => createElement("header", { "data-testid": "header", "data-subtitle": p.subtitle ?? "" }, p.title) },
    RunActions: { RunActions: (p) => createElement("div", { "data-testid": "run-actions", "data-hide": p.hide.join(",") }) },
    RunPayload: { RunPayload: box("run-payload") },
    RunTokens: { RunTokens: box("run-tokens") },
  };
}

test("a run on the phone shows its state, facts, steps, tasks and links", async () => {
  const opened = [];
  const { RunPage } = load("mobile/RunPage.tsx", runPageStubs(RUN), {
    window: { setInterval: () => 1, clearInterval: noop, scrollTo: noop, setTimeout, clearTimeout },
  });
  const view = await render(RunPage, {
    runId: "r1", title: "Run", onBack: noop,
    links: { onOpenChat: (...args) => opened.push(args), onOpenWorkItem: (item) => opened.push(item.key) },
  });
  const root = view.root;
  assert.equal(text(root.findByProps({ "data-testid": "header" })), "PET-7 · Add login");
  const facts = root.findByProps({ className: "m-facts" }).findAllByType("dt").map((dt) => text(dt));
  assert.ok(facts.includes("Branch"));
  assert.equal(root.findAllByProps({ className: "m-task" }).length, 2);
  assert.equal(text(root.findByProps({ id: "m-tasks" })), "Tasks");
  assert.equal(root.findAllByProps({ "data-testid": "run-tokens" }).length, 1);
  assert.equal(root.findByProps({ "data-testid": "run-actions" }).props["data-hide"], "");
  const rows = root.findAllByProps({ className: "m-row m-row-icon" });
  assert.match(text(rows[rows.length - 1]), /Work item PET-7/);
  act(() => rows[rows.length - 1].props.onClick());
  assert.deepEqual(opened, ["PET-7"]);
  act(() => view.unmount());
});

test("the new chat sheet offers Workspaces, Macs and the Server and starts on the chosen one", async () => {
  const { NewChatSheet } = load("mobile/NewChatSheet.tsx", {
    mobileApi: {
      loadDevices: async () => ({ items: [{ id: "d1", name: "Dana's Mac", connected: true, folders: ["/Users/dana/app"] }] }),
      loadPolicy: async () => ({ enabled: true }),
      send: noop,
    },
    ServerOptionsBar: { ServerOptionsBar: box("server-options") },
    TurnOptionsBar: { TurnOptionsBar: box("turn-options") },
    useTurnOptions: { useTurnOptions: () => [{ model: "", permissionMode: "default", effort: "" }, noop] },
    icons: { Icon: icon },
  });
  const view = await render(NewChatSheet, {
    projects: [{ id: "p1", name: "Petclinic" }, { id: "p2", name: "Shop" }], initialProjectId: "p2",
    onClose: noop, onStarted: noop,
  });
  const root = view.root;
  assert.equal(root.findByProps({ role: "dialog" }).props["aria-label"], "New chat");
  assert.equal(root.findByProps({ id: "m-workspace" }).props.value, "p2");
  const devices = root.findByProps({ id: "m-device" }).findAllByType("option").map((option) => text(option));
  assert.equal(devices[devices.length - 1], "Octryx server");
  const labels = root.findAllByType("label").map((label) => text(label));
  assert.ok(labels.includes("Message"));
  const start = root.findByProps({ className: "m-primary m-full" });
  assert.equal(start.props.disabled, true);
  assert.match(text(start), /^Start on /);
  act(() => view.unmount());
});

test("the phone tab screen shows the chosen tab, the More links and the tab bar", async () => {
  const seen = {};
  const page = (name) => (p) => { seen[name] = p; return createElement("section", { "data-testid": name }); };
  const { MobileTabScreen } = load("mobile/MobileTabScreen.tsx", {
    ChatsPage: { ChatsPage: page("chats") }, HomePage: { HomePage: page("home") },
    mobileHomeTiles: { homeTiles: () => ["tile"] }, mobileSession: { signOutPhone: async () => {} },
    MorePage: { MorePage: page("more") }, RunsPage: { RunsPage: page("runs") },
    StartRunSheet: { StartRunSheet: page("start-run") },
    TabBar: { TabBar: (p) => { seen.tabs = p; return createElement("nav", { "data-testid": "tab-bar" }); } },
    TasksPage: { TasksPage: page("work") },
  }, { window: { scrollTo: noop } });
  const props = {
    tab: "more", setTab: noop, switcher: null, workspace: "p1", workspaceNames: { p1: "Petclinic" }, needs: [{ key: "a" }],
    shownApprovals: [{ id: "x" }, { id: "y" }], shownThreads: [], shownCases: [], sessions: [], liveSessions: [],
    localSessions: [], usage: null, loading: false, error: "", devices: [{ connected: true }, { connected: false }],
    runRows: [], openTasks: 1, myTasks: 0, session: { id: "s" }, roleWorkspaceName: "Petclinic",
    phonePages: [{ key: "k1", pluginName: "Weather", slot: { title: "Forecast" } }], workMine: false, setWorkMine: noop,
    startingRun: true, setStartingRun: noop, setPhase: noop, openPage: noop, openItem: noop, openThread: noop, openLocal: noop,
  };
  const view = await render(MobileTabScreen, props);
  assert.equal(view.root.findByProps({ className: "m-screen m-tabbed" }).type, "div");
  const json = (value) => JSON.stringify(value);
  assert.equal(json(seen.more.links.map((link) => [link.label, link.detail])), json([
    ["Your Macs", "1 of 2 online"], ["Seat", "Your own subscription and what the Workspace allows"],
    ["Operations", "What runs where, and what is stuck"], ["My role", "Roles and tools in Petclinic"],
    ["Forecast", "Weather · plugin"],
  ]));
  assert.equal(view.root.findAllByProps({ "data-testid": "start-run" }).length, 1);
  assert.equal(json(seen.tabs.tabs.map((tab) => [tab.key, tab.badge ?? null])), json([
    ["home", 3], ["chats", null], ["runs", null], ["work", null], ["more", null],
  ]));
  assert.equal(seen.tabs.active, "more");
  act(() => view.update(createElement(MobileTabScreen, { ...props, tab: "home" })));
  assert.equal(json(seen.home.tiles), json(["tile"]));
  assert.equal(seen.home.approvals.length, 2);
  act(() => view.unmount());
});

test("the phone app signs in, loads its data and shows the tab screen for the chosen Workspace", async () => {
  const seen = {};
  const location = { hash: "", pathname: "/m/" };
  const windowStub = {
    location, history: { replaceState: noop }, addEventListener: noop, removeEventListener: noop,
    setInterval: () => 1, clearInterval: noop, localStorage: { getItem: () => null, setItem: noop },
  };
  const { MobileApp } = load("mobile/MobileApp.tsx", {
    ConfirmPage: { ConfirmPage: box("confirm") }, ConnectPage: { ConnectPage: box("connect") },
    mobileSession: { claimPhone: async () => {}, onSignedOut: () => noop, startSession: async () => ({ id: "phone" }) },
    mobileDetailPages: { detailPage: () => null },
    mobileAppLoad: {
      loadMobileAppData: async (choice, setters) => {
        setters.setProjects([{ id: "p1", name: "Petclinic" }]);
        setters.setItems([]);
        setters.setLoading(false);
      },
    },
    MobileTabScreen: { MobileTabScreen: (p) => { seen.tabs = p; return createElement("div", { "data-testid": "tabs" }); } },
    PluginPage: { phoneFetch: noop },
    usePluginSlots: { usePluginSlots: () => ({ entries: [] }) },
    pluginUiModel: { slotsOf: () => [] },
    OctryxMark: { OctryxMark: box("mark") },
    PairPage: { PairPage: box("pair") },
    pullToRefresh: { useRefreshEvent: noop },
    useMobileOpeners: { useMobileOpeners: () => ({ openThread: noop, openLocal: noop, openItem: noop }) },
    WorkspaceSwitcher: { WorkspaceSwitcher: box("switcher") },
  }, { window: windowStub, document: { hidden: false, visibilityState: "visible", addEventListener: noop, removeEventListener: noop } });
  const view = await render(MobileApp, {});
  await flush();
  assert.equal(view.root.findAllByProps({ "data-testid": "tabs" }).length, 1);
  assert.equal(seen.tabs.tab, "home");
  assert.deepEqual(seen.tabs.workspaceNames, { p1: "Petclinic" });
  assert.deepEqual(seen.tabs.session, { id: "phone" });
  assert.equal(seen.tabs.loading, false);
  assert.equal(Object.keys(seen.tabs).length, 31);
  act(() => view.unmount());
});
