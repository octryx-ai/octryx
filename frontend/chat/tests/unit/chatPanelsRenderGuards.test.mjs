// Render guards for chat components (canvas, area rail, chat area, thread group, linked accounts, trace modal): key
// text and structure stay the same when the components are split into smaller parts. Heavy children and network
// modules are stubbed by module name.
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

test("the canvas panel shows its title, four tools, five colours and undo/clear", async () => {
  const { CanvasPanel } = load("chat/CanvasPanel.tsx");
  const tools = [];
  const view = await render(CanvasPanel, {
    activeTool: "rect", setActiveTool: (tool) => tools.push(tool), activeColor: "#ef4444", setActiveColor: noop,
    setShowCanvas: noop, canvasRef: { current: null }, canvasWsRef: { current: null }, isDrawingRef: { current: false },
    lastPosRef: { current: null }, drawElement: noop, clearCanvas: noop,
  });
  const root = view.root;
  assert.equal(text(root.findByProps({ className: "canvas-panel__title" })), "Canvas");
  const titles = root.findAllByType("button").map((button) => button.props.title);
  assert.deepEqual(titles, ["Close canvas", "pencil", "rect", "circle", "eraser", "#ffffff", "#ef4444", "#facc15",
    "#4ade80", "#60a5fa", "Undo", "Clear"]);
  assert.equal(root.findByProps({ title: "rect" }).props.className, "canvas-tool-btn canvas-tool-btn--active");
  assert.equal(root.findByProps({ title: "#ef4444" }).props.className, "canvas-color-btn canvas-color-btn--active");
  act(() => root.findByProps({ title: "eraser" }).props.onClick());
  assert.deepEqual(tools, ["eraser"]);
  assert.equal(root.findAllByType("canvas").length, 1);
  act(() => view.unmount());
});

function areaRailStubs() {
  return {
    ChatShellIcons: { BrandGlyph: box("brand-glyph"), ThemeIcon: (p) => createElement("i", { "data-theme": p.theme }) },
    CompanionHost: { CompanionLogoTrigger: (p) => createElement("button", { "data-testid": "logo", className: p.className }) },
    GlobalWorkspaceSwitch: { GlobalWorkspaceSwitch: (p) => createElement("div", { "data-testid": "switch", "data-global": String(p.allowGlobal) }) },
    useActiveWorkspace: { useActiveWorkspace: () => ["w1"] },
    useSetupProgress: { useSetupProgress: () => "Setup 2 of 5 done" },
    personalSettingsTab: { openPersonalTab: noop },
    AreaRailIcons: new Proxy({}, { get: (_, name) => () => createElement("i", { "data-icon": String(name) }) }),
  };
}

test("the area rail lists destinations, setup progress, help, theme and the open account menu", async () => {
  const { AreaRail } = load("chat/AreaRail.tsx", areaRailStubs());
  const opened = [];
  const view = await render(AreaRail, {
    activeBranding: { app_name: "", logo_url: "", logo_svg: "" }, activeArea: "chat", brandFallbackLabel: "O",
    chatTheme: "dark", currentUserIsAdmin: true, currentUserCanReadWork: true, currentUserEmail: "dana@example.org",
    currentUserName: "dana", projects: [], openSettingsTab: (...args) => opened.push(args), onOpenHelp: noop,
    profileDropdownOpen: true, setActiveArea: noop, setChatTheme: noop, setProfileDropdownOpen: noop,
  });
  const root = view.root;
  const labels = root.findAllByType("button").map((button) => button.props["aria-label"] ?? text(button));
  assert.ok(labels.includes("Chat"));
  assert.ok(labels.includes("Setup 2 of 5 done · Open the setup guide"));
  assert.ok(labels.includes("Open page help"));
  assert.ok(labels.includes("Switch to light theme"));
  assert.equal(text(root.findByProps({ "data-testid": "rail-setup-progress" })), "Setup2/5");
  assert.equal(root.findByProps({ "aria-current": "page" }).props["aria-label"], "Chat");
  assert.equal(text(root.findByProps({ className: "area-rail__btn area-rail__account area-rail__account--open" })), "D");
  const items = root.findAllByProps({ className: "profile-dropdown__item" }).map((item) => text(item));
  assert.deepEqual(items, ["Profile", "My settings", "Platform settings", "Usage & costs", "Setup guide", "Help for this page"]);
  assert.equal(text(root.findByProps({ className: "profile-dropdown__email" })), "dana@example.org");
  act(() => root.findAllByProps({ className: "profile-dropdown__item" })[2].props.onClick());
  assert.deepEqual(opened, [["adminProblems", "admin"]]);
  act(() => view.unmount());
});

test("the chat area wraps the sidebar and the workspace and passes every prop on", async () => {
  const seen = {};
  const { ChatAppArea } = load("chat/ChatAppArea.tsx", {
    SidebarShell: { SidebarShell: (p) => { seen.sidebar = p; return createElement("aside", { "data-testid": "sidebar" }); } },
    WorkspaceMainArea: { WorkspaceMainArea: (p) => { seen.main = p; return createElement("main", { "data-testid": "main" }); } },
  });
  let collapsed = false;
  const view = await render(ChatAppArea, {
    sidebarOpen: true, chatSidebarCollapsed: true, setSidebarOpen: noop, chatState: { id: "s" }, selectedSession: { id: "t1" },
    setChatSidebarCollapsed: (fn) => { collapsed = fn(collapsed); }, handleCleanWorkspace: noop, composerValue: "hi",
    handlePinThread: noop, canDeleteThreads: true,
  });
  assert.equal(view.root.findByProps({ className: "chat-app chat-app--sidebar-open chat-app--sessions-collapsed" }).type, "div");
  assert.equal(Object.keys(seen.sidebar).length, 17);
  assert.equal(Object.keys(seen.main).length, 129);
  assert.equal(seen.main.composerValue, "hi");
  assert.equal(seen.main.handleCleanWorkspace, noop);
  assert.equal(seen.sidebar.onPinThread, noop);
  assert.equal(seen.sidebar.collapsed, true);
  seen.sidebar.onToggleCollapsed();
  assert.equal(collapsed, true);
  act(() => view.unmount());
});

const thread = (id, title, fields = {}) => ({ id, title, status: "completed", updatedAt: new Date().toISOString(),
  createdAt: new Date().toISOString(), ...fields });

test("a thread group shows its title, count, sections, rows and load more", async () => {
  const { ThreadGroupSection } = load("chat/ThreadGroupSection.tsx", {
    ThreadGroupBulkParts: { GroupCheckbox: box("group-check"), GroupBanner: box("group-banner") },
    ThreadDraftRow: { ThreadDraftRow: box("draft-row") },
    ThreadGroupNode: { createThreadNodeRenderer: () => (t) => createElement("div", { key: t.id, "data-testid": "node" }, t.title) },
    threadSidebarIcons: { ThreadChevronIcon: box("chevron"), ThreadFolderIcon: box("folder") },
  }, { window: { addEventListener() {}, removeEventListener() {}, setTimeout, clearTimeout } });
  const group = { projectId: "p1", projectName: "Petclinic", sessions: [thread("t1", "One", { isSelected: true }), thread("t2", "Two")],
    totalThreadCount: 30, hasMore: true, pageSize: 20 };
  const view = await render(ThreadGroupSection, {
    group, onSelect: noop, onPinToggle: noop, onRename: noop, onArchive: noop, onExport: noop, onExportAnalysis: noop,
    onDelete: noop, onLoadMore: noop, onDraftSelect: noop,
  });
  const root = view.root;
  assert.equal(text(root.findByProps({ className: "thread-group__title-name" })), "Petclinic");
  assert.equal(text(root.findByProps({ className: "thread-group__title-meta" })), "30");
  assert.equal(root.findByProps({ className: "thread-group__title-button" }).props["aria-expanded"], true);
  assert.equal(root.findAllByProps({ "data-testid": "draft-row" }).length, 1);
  assert.deepEqual(root.findAllByProps({ "data-testid": "node" }).map((node) => text(node)), ["One", "Two"]);
  assert.equal(root.findByProps({ role: "tree" }).props["aria-label"], "Chats in Petclinic");
  assert.equal(text(root.findByProps({ className: "thread-group__load-more" })), "Show 20 more · 28 not shown");
  act(() => view.unmount());
});

test("linked accounts list each platform with its account, badge and actions", async () => {
  const { LinkedAccountsPanel } = load("chat/profile/LinkedAccountsPanel.tsx", {
    linkedAccountsApi: {
      loadLinkedAccounts: async () => ({
        workspaces: [{ id: "w1", name: "Petclinic" }],
        platforms: [
          { platform: "atlassian", label: "Atlassian", identifier_kind: "account_id", description: "Jira Cloud account" },
          { platform: "github", label: "GitHub", description: "GitHub login" },
        ],
        accounts: [{ platform: "atlassian", identifier: "5b10a", display_name: "Dana", verification_status: "verified" }],
      }),
      removeLinkedAccount: noop, saveLinkedAccount: noop, verifyLinkedAccount: noop,
    },
  });
  const view = await render(LinkedAccountsPanel, { userId: "me", ownAccounts: true });
  const root = view.root;
  assert.match(text(root.findByProps({ className: "admin-panel__hint" })), /your linked account/);
  assert.equal(root.findByType("select").props.value, "w1");
  assert.equal(root.findAllByProps({ className: "linked-accounts__row" }).length, 2);
  const atlassian = root.findByProps({ "data-testid": "linked-account-atlassian" });
  assert.match(text(atlassian), /5b10aDana/);
  assert.equal(JSON.stringify(atlassian.findAllByType("button").map((button) => text(button))), JSON.stringify(["Verify", "Change", "Unlink"]));
  assert.equal(text(atlassian.findByProps({ className: "work-badge work-badge--active" })), "Verified");
  const github = root.findByProps({ "data-testid": "linked-account-github" });
  assert.equal(JSON.stringify(github.findAllByType("button").map((button) => text(button))), JSON.stringify(["Link"]));
  act(() => atlassian.findAllByType("button").find((button) => text(button) === "Change").props.onClick());
  assert.equal(root.findAllByProps({ className: "linked-accounts__edit" }).length, 1);
  assert.equal(root.findByProps({ role: "group" }).props["aria-label"], "How to link");
  act(() => atlassian.findAllByType("button").find((button) => text(button) === "Unlink").props.onClick());
  assert.equal(root.findAllByProps({ className: "admin-panel__danger-btn" }).map((button) => text(button)).join(), "Confirm unlink");
  act(() => view.unmount());
});

test("the execution trace shows token, cache and working-set tiles and the raw sections", async () => {
  const { TurnTraceModal } = load("chat/traceTurnTraceModal.tsx", {}, { navigator: {} });
  const view = await render(TurnTraceModal, {
    open: true, onClose: noop,
    trace: {
      provider: "bedrock", model: "m",
      usage: { prompt_tokens: 1200, completion_tokens: 300, bedrock_cache_read_input_tokens: 800,
        bedrock_cache_cost_pricing_status: "priced" },
      contextSnapshot: { within_turn_working_set: { tool_messages_total: 4, estimated_prompt_tokens: 900 } },
    },
  });
  const root = view.root;
  assert.equal(text(root.findByProps({ className: "admin-panel__title" })), "bedrock / m");
  const tiles = root.findAllByProps({ className: "turn-trace-usage__item" }).map((item) => text(item));
  assert.ok(tiles.includes("Cache pricingpriced"));
  assert.ok(tiles.some((tile) => tile.startsWith("Input")));
  assert.ok(tiles.some((tile) => tile.startsWith("Cache read")));
  const headings = root.findAllByType("h4").map((h) => text(h));
  for (const heading of ["Input", "Context", "Tools", "Output", "Usage"]) assert.ok(headings.includes(heading));
  act(() => view.unmount());
});
