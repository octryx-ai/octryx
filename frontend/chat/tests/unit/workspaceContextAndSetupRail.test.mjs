// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceContextAndSetupRail.test.mjs
//
// One Workspace context for the whole app, an existing chat without
// messages is not a new chat, the rail says "Setup 4/7" in words, two runs of one workflow are told apart and a
// waiting run never reads "Working".
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { workspaceInitials, workspaceSwitchLabel } from "../../src/chat/workspace/globalWorkspaceModel.ts";
import { runName, runStatePhrase } from "../../src/chat/companion/companionLabels.ts";
import { readRunningAgent } from "../../src/chat/companion/companionRead.ts";
import { jobStateLabel, jobTitle, readJob } from "../../src/chat/companion/companionJobModel.ts";

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

// A browser stand-in that keeps localStorage, history and the workspace change event, so one switch drives all.
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

test("The switch names the Workspace and its initials", () => {
  assert.equal(workspaceInitials("Acme"), "AC");
  assert.equal(workspaceInitials("ux first run"), "UF");
  assert.equal(workspaceInitials("ux-check-create"), "UC");
  assert.equal(workspaceInitials(""), "–");
  // Initials come from letters and digits only ("Acme (demo)" showed "A(").
  assert.equal(workspaceInitials("Acme (demo)"), "AD");
  assert.equal(workspaceInitials("Private · admin"), "PA");
  assert.equal(workspaceInitials("(beta)"), "BE");
  assert.equal(workspaceInitials("Team 42"), "T4");
  assert.equal(workspaceInitials("Zürich Ops"), "ZO");
  assert.equal(workspaceInitials("· – ·"), "–");
  assert.equal(workspaceSwitchLabel("Test"), "Workspace: Test · change");
  assert.equal(workspaceSwitchLabel(null), "No workspace selected · choose one");
});

test("One switch drives every area that reads the shared choice, and the address follows", async () => {
  const win = browser("?area=knowledge");
  const load = loader({ window: win, document: { documentElement: {} } });
  const { setActiveWorkspaceUser } = load("chat/activeWorkspace.ts");
  setActiveWorkspaceUser("u-alex");
  const { GlobalWorkspaceSwitch } = load("chat/workspace/GlobalWorkspaceSwitch.tsx");
  const { useActiveWorkspace } = load("chat/useActiveWorkspace.ts");
  const seen = [];
  function Area() {
    const [workspaceId] = useActiveWorkspace(PROJECTS);
    seen.push(workspaceId);
    return createElement("p", { "data-testid": "area" }, workspaceId || "none");
  }
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement("div", null,
      createElement(GlobalWorkspaceSwitch, { projects: PROJECTS, fallbackWorkspaceId: "ws-test" }), createElement(Area)));
  });
  assert.match(byTestId(view, "global-workspace-switch")[0].findByType("button").props["aria-label"], /Workspace: Test/);
  await act(async () => { byTestId(view, "global-workspace-switch")[0].findByType("button").props.onClick(); });
  await act(async () => { byTestId(view, "global-workspace-item-ws-rs")[0].props.onClick(); });
  assert.equal(text(byTestId(view, "area")[0]), "ws-rs", "the area follows the one switch");
  assert.match(byTestId(view, "global-workspace-switch")[0].findByType("button").props["aria-label"], /Acme Orders/);
  assert.match(win.location.search, /workspace_id=ws-rs/, "workspace_id in the address follows the choice");
});

test("An address workspace_id is the context on load", async () => {
  const win = browser("?area=work&workspace_id=ws-rs");
  const load = loader({ window: win, document: { documentElement: {} } });
  load("chat/activeWorkspace.ts").setActiveWorkspaceUser("u-alex");
  const { GlobalWorkspaceSwitch } = load("chat/workspace/GlobalWorkspaceSwitch.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(GlobalWorkspaceSwitch, { projects: PROJECTS, fallbackWorkspaceId: "ws-test" })); });
  assert.match(byTestId(view, "global-workspace-switch")[0].findByType("button").props["aria-label"], /Acme Orders/);
});

test("Opening an existing chat makes its Workspace the context; choosing another one there starts a new chat", async () => {
  const win = browser("?session_id=s1");
  const load = loader({ window: win, document: { documentElement: {} } });
  const { storeWorkspacePreference, readStoredWorkspacePreference } = load("chat/activeWorkspace.ts");
  const { useChatWorkspaceSync } = load("chat/useActiveWorkspace.ts");
  const left = [];
  function Chat({ selected }) {
    useChatWorkspaceSync("u-alex", selected, () => {}, PROJECTS, true, false, true, (next) => left.push(next));
    return null;
  }
  // The person chose Acme Orders elsewhere before; the chat on screen is in Test.
  load("chat/activeWorkspace.ts").setActiveWorkspaceUser("u-alex");
  storeWorkspacePreference("ws-rs");
  await act(async () => { TestRenderer.create(createElement(Chat, { selected: "ws-test" })); });
  assert.equal(readStoredWorkspacePreference(), "ws-test", "the open chat is the context");
  await act(async () => { storeWorkspacePreference("ws-rs"); });
  assert.deepEqual(left, ["ws-rs"], "another Workspace while the chat is on screen leaves it for a new chat there");
});

test("Workspace-scoped pages carry no switch of their own", () => {
  for (const file of ["chat/work/WorkAreaWorkspace.tsx", "chat/knowledge/KnowledgeAreaWorkspace.tsx", "chat/agents/AgentsAreaWorkspace.tsx",
    "chat/coding/CodingAreaWorkspace.tsx", "chat/coding/CodingWorkspaceEntry.tsx", "chat/setup/SetupGuidePage.tsx"]) {
    assert.doesNotMatch(read(file), /WorkspaceScopeSelect/, file);
  }
});

test("An existing chat without messages shows one line, not the welcome screen", () => {
  const view = read("chat/WorkspacePrimaryContent.tsx");
  assert.match(view, /emptyState=\{selectedSession\?\.id \? \([\s\S]*?No messages yet\.[\s\S]*?\) : \([\s\S]*?<EmptyState/);
});

test("The rail says Setup n/m in words and links to the setup guide", () => {
  const rail = read("chat/AreaRail.tsx");
  assert.match(rail, /<span className="area-rail__setup-label">Setup<\/span>/);
  assert.match(rail, /onClick=\{\(\) => setActiveArea\("help"\)\}/);
  assert.match(read("chat/setup/setupGuideModel.ts"), /requiredOpen === 0\) return null/, "gone once every required step is done");
});

test("Two runs of one workflow carry their ticket; a waiting run never reads Working", () => {
  assert.equal(runName("BRD-14", "Add capitalize_words", "Feature delivery (TDD)"), "BRD-14 Add capitalize_words");
  assert.equal(runName("", "", "Feature delivery (TDD)"), "Feature delivery (TDD)");
  const running = readRunningAgent({ run_id: "8f2d50c4", title: "Feature delivery (TDD)", ticket_key: "BRD-14", state: "working",
    status: "waiting", current_node: "merged" });
  assert.equal(running.label, "BRD-14 Feature delivery (TDD)");
  assert.equal(runStatePhrase(running.status, running.currentNode, running.waitingKind, "Working"), "Waiting for merge");
  assert.equal(runStatePhrase("waiting", "review", "approval", "Working"), "Waiting for approval");
  assert.equal(runStatePhrase("waiting", "review", "", "Working"), "Waiting");
  assert.equal(runStatePhrase("running", "implement", "", "Working"), "Working");
  const job = readJob({ run_id: "r1", title: "Feature delivery (TDD)", work_item: { id: "w1", key: "BRD-14", title: "Add capitalize_words" },
    state: "working", status: "waiting", current_node: { id: "merged", title: "Merged" } });
  assert.equal(jobTitle(job), "BRD-14 Add capitalize_words");
  assert.equal(jobStateLabel(job), "Waiting for merge");
});
