// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/chatWorkspaceGlobalSwitch.test.mjs
//
// Review point 7: the chat composer has no Workspace select of its own; the one global switch is the
// Workspace choice. Chatting without a Workspace ("Global", administrators only) moved into that switch:
// a new chat takes it, an open chat of a Workspace is left for a new chat without one. Non-administrators never see it.
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

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const read = (relative) => fs.readFileSync(path.join(SRC, relative), "utf8");
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));

function loader(extra) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, URL, URLSearchParams, Error, Object, Array, String, Set, Map, JSON, CustomEvent,
      ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return (relative) => loadFile(path.join(SRC, relative));
}

function browser(search = "") {
  const store = new Map();
  const listeners = new Map();
  const win = {
    location: { search, href: `http://localhost/chat${search}` },
    localStorage: { getItem: (key) => store.get(key) ?? null, setItem: (key, value) => store.set(key, value) },
    history: { state: null, replaceState(_state, _title, href) { const url = new URL(href); win.location.search = url.search; win.location.href = url.toString(); } },
    addEventListener: (type, fn) => listeners.set(type, [...(listeners.get(type) ?? []), fn]),
    removeEventListener: (type, fn) => listeners.set(type, (listeners.get(type) ?? []).filter((entry) => entry !== fn)),
    dispatchEvent: (event) => { for (const fn of listeners.get(event.type) ?? []) fn(event); return true; },
  };
  return win;
}

const PROJECTS = [{ id: "ws-test", name: "Test" }, { id: "ws-rs", name: "Acme Orders" }];

async function openSwitch(props) {
  const win = browser("?area=chat");
  const load = loader({ window: win, document: { documentElement: {} } });
  load("chat/activeWorkspace.ts").setActiveWorkspaceUser("u-alex");
  const { GlobalWorkspaceSwitch } = load("chat/workspace/GlobalWorkspaceSwitch.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(GlobalWorkspaceSwitch, { projects: PROJECTS, fallbackWorkspaceId: "ws-test", ...props })); });
  await act(async () => { byTestId(view, "global-workspace-switch")[0].findByType("button").props.onClick(); });
  return { view, win, load };
}

test("an administrator chooses Global in the one switch; the choice is stored as 'no workspace'", async () => {
  const { view, load } = await openSwitch({ allowGlobal: true });
  const global = byTestId(view, "global-workspace-item-global");
  assert.equal(global.length, 1);
  assert.equal(text(global[0]), "–Global · no workspace");
  assert.equal(global[0].props["aria-checked"], false);
  await act(async () => { global[0].props.onClick(); });
  assert.equal(load("chat/activeWorkspace.ts").readStoredWorkspacePreference(), "");
  assert.match(byTestId(view, "global-workspace-switch")[0].findByType("button").props["aria-label"], /No workspace selected/);
  act(() => view.unmount());
});

test("without the right to chat globally the switch offers Workspaces only", async () => {
  const { view } = await openSwitch({});
  assert.equal(byTestId(view, "global-workspace-item-global").length, 0);
  assert.equal(byTestId(view, "global-workspace-item-ws-rs").length, 1);
  act(() => view.unmount());
});

test("Global from the switch reaches a new chat, and leaves an open chat of a Workspace for a new one", async () => {
  const win = browser("?new=true");
  const load = loader({ window: win, document: { documentElement: {} } });
  const { storeWorkspacePreference, setActiveWorkspaceUser } = load("chat/activeWorkspace.ts");
  const { useChatWorkspaceSync } = load("chat/useActiveWorkspace.ts");
  setActiveWorkspaceUser("u-alex");
  storeWorkspacePreference("ws-test");
  const chosen = [];
  const left = [];
  function Chat({ selected, hasSession, allowGlobal }) {
    useChatWorkspaceSync("u-alex", selected, (next) => chosen.push(next), PROJECTS, hasSession, allowGlobal, true, (next) => left.push(next));
    return null;
  }
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Chat, { selected: "ws-test", hasSession: false, allowGlobal: true })); });
  await act(async () => { storeWorkspacePreference(""); });
  assert.deepEqual(chosen, [""], "a new chat takes Global");
  await act(async () => { view.update(createElement(Chat, { selected: "ws-rs", hasSession: true, allowGlobal: true })); });
  await act(async () => { storeWorkspacePreference(""); });
  assert.deepEqual(left, [""], "an open chat of a Workspace is left for a new chat without one");
  act(() => view.unmount());

  // Without the right, a "no workspace" event changes nothing in the chat.
  const plain = [];
  await act(async () => {
    view = TestRenderer.create(createElement(function Plain() {
      useChatWorkspaceSync("u-alex", "ws-test", (next) => plain.push(next), PROJECTS, false, false, true, () => plain.push("left"));
      return null;
    }));
  });
  await act(async () => { storeWorkspacePreference(""); });
  assert.deepEqual(plain, []);
  act(() => view.unmount());
});

test("the rail and the compact menu offer Global to administrators only; the composer carries no Workspace select", () => {
  assert.match(read("chat/AreaRail.tsx"), /<GlobalWorkspaceSwitch [^>]*allowGlobal=\{currentUserIsAdmin\}/);
  assert.match(read("chat/CompactAreaMenu.tsx"), /<GlobalWorkspaceSwitch variant="compact"[^>]*allowGlobal=\{isAdmin\}/);
  const pills = read("chat/composer/ComposerRoutingPills.tsx");
  assert.doesNotMatch(pills, /Project selection|setSelectedProjectId|FolderIcon/);
});
