// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/chatMessageTools.test.mjs
//
// Chat follow-up: an assistant message shows Copy and Retry with everything else in its "⋯" menu; a turn's
// tool steps fold into one line with failures kept visible; a source marker [n] opens the Sources panel; the chat list
// follows the active Workspace with an explicit "All workspaces" switch.
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

const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

function load(relative) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, URL, URLSearchParams,
      window: { innerWidth: 1200, addEventListener() {}, removeEventListener() {} },
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".ts", ".tsx"]) {
            const candidate = base + ext;
            if (fs.existsSync(candidate) && fs.readdirSync(path.dirname(candidate)).includes(path.basename(candidate))) {
              return loadFile(candidate);
            }
          }
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

const menuInput = (overrides = {}) => {
  const calls = [];
  const record = (name) => async () => { calls.push(name); };
  return {
    calls,
    input: {
      retryPrompt: "Explain the release", retrying: false, actionsDisabled: false,
      triggerRetryPrompt: record("prompt"), speaking: false, toggleSpeak: () => calls.push("read"),
      hasTurnTrace: true, thinkingOpen: true, thinkingLoading: false, toggleThinking: record("think"),
      performanceOpen: false, performanceLoading: true, togglePerformance: record("perf"),
      traceLoading: false, openTrace: record("trace"), ...overrides,
    },
  };
};

test("the message menu holds Prompt, Read and the diagnostics, in a fixed order, calling the same handlers", () => {
  const { assistantMessageMenuItems } = load("chat/messageMoreMenu.ts");
  const { calls, input } = menuInput();
  const items = assistantMessageMenuItems(input);
  const plainRows = JSON.parse(JSON.stringify(items.map((item) => [item.label, Boolean(item.disabled), item.checked ?? null])));
  assert.deepEqual(plainRows, [
    ["Retry the preceding prompt", false, null],
    ["Read aloud", false, null],
    ["Thinking details", false, true],
    ["Loading performance…", true, false],
    ["Open trace", false, null],
  ]);
  items.forEach((item) => item.onSelect());
  assert.deepEqual(calls, ["prompt", "read", "think", "perf", "trace"]);
  const plain = assistantMessageMenuItems(menuInput({ retryPrompt: null, hasTurnTrace: false, speaking: true }).input);
  assert.deepEqual(JSON.parse(JSON.stringify(plain.map((item) => item.label))), ["Stop reading"], "diagnostics only for a traced turn");
});

test("an assistant message shows Copy, Retry and one ⋯ menu; a user message keeps Copy, Edit and Draft", () => {
  const { MessageBubbleActions } = load("chat/MessageBubbleActions.tsx");
  const { assistantMessageMenuItems } = load("chat/messageMoreMenu.ts");
  const noop = async () => {};
  const base = {
    compact: true, iconOnly: true, isThinking: false, displayContent: "Answer", copied: false, copyMessage: noop,
    actionsDisabled: false, startEditMessage() {}, reused: false, reuseMessage() {}, retryPrompt: "Explain",
    retrying: false, triggerRetryFromHere: noop,
  };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(MessageBubbleActions, {
      ...base, isUser: false, menuItems: assistantMessageMenuItems(menuInput().input),
    }));
  });
  const labels = view.root.findAllByType("button").map((button) => button.props["aria-label"]);
  assert.deepEqual(labels, ["Copy message", "Rerun the thread from this assistant turn", "More actions for this answer"]);
  act(() => view.root.findByProps({ "aria-label": "More actions for this answer" }).props.onClick({
    currentTarget: { getBoundingClientRect: () => ({ bottom: 10, right: 100 }) },
  }));
  assert.deepEqual(view.root.findAllByProps({ role: "menuitem" }).map(text).concat(
    view.root.findAllByProps({ role: "menuitemcheckbox" }).map(text)),
  ["Retry the preceding prompt", "Read aloud", "Open trace", "Thinking details✓", "Loading performance…"]);
  act(() => view.update(createElement(MessageBubbleActions, { ...base, isUser: true })));
  assert.deepEqual(view.root.findAllByType("button").map((button) => button.props["aria-label"]),
    ["Copy message", "Edit this message and rerun from here", "Reuse this message as draft"]);
  act(() => view.unmount());
  const header = fs.readFileSync(path.join(SRC, "chat/MessageBubbleHeader.tsx"), "utf8");
  assert.doesNotMatch(header, /MessageBubbleMetaControls/);
});

const event = (id, toolName, status, durationMs, result = null) => ({ id, toolName, status, durationMs, result, parameters: {}, createdAt: null });

test("tool steps fold into one line; failures stay listed one per line", () => {
  const { foldToolSteps } = load("chat/toolStepFoldModel.ts");
  assert.equal(foldToolSteps([]), null);
  assert.equal(foldToolSteps([event("i", "batch", "success", 5)]), null, "internal tools are not counted");
  const done = foldToolSteps([
    event("a", "knowledge_search", "success", 4000),
    event("b", "jira_get_issue", "error", 1500, { message: "Timeout talking to Jira after 30 s" }),
    event("c", "confluence_get_page", "success", 6500),
    event("d", "web_fetch", "failed", 0),
  ]);
  assert.equal(done.label, "Used 4 tools · 12 s");
  assert.deepEqual(done.failures.map((failure) => failure.text),
    ["Jira Get Issue failed: Timeout talking to Jira after 30 s", "Web Fetch failed"]);
  assert.equal(foldToolSteps([event("a", "knowledge_search", "success", 300)]).label, "Used 1 tool · 300 ms");
  const running = foldToolSteps([event("a", "knowledge_search", "success", 300), event("b", "web_fetch", "running", 0)]);
  assert.deepEqual([running.label, running.running], ["Using tools · 2 so far", true]);
});

test("the folded line opens the existing per-tool list and keeps failures outside the fold", () => {
  const { ToolStepFold } = load("chat/ToolStepFold.tsx");
  let view;
  act(() => {
    view = TestRenderer.create(createElement(ToolStepFold, {
      events: [event("a", "knowledge_search", "success", 2000), event("b", "web_fetch", "error", 0)],
    }, createElement("div", { "data-testid": "tool-list" })));
  });
  const details = view.root.findByType("details");
  assert.equal(text(details.findByType("summary")), "Used 2 tools · 2.0 s");
  assert.equal(details.findAllByProps({ "data-testid": "tool-list" }).length, 1);
  const failures = view.root.findByProps({ "aria-label": "Failed tool steps" });
  assert.deepEqual(failures.findAllByType("li").map(text), ["Web Fetch failed"]);
  act(() => view.update(createElement(ToolStepFold, { events: [] }, createElement("div"))));
  assert.equal(view.toJSON(), null);
  act(() => view.unmount());
});

test("a numeric source marker opens the Sources panel; other links keep opening in a new tab", () => {
  const { isCitationMarker, citationMarkerTarget } = load("chat/evidence/answerSourceLinks.ts");
  assert.deepEqual(["1", "[2]", " [12] ", "Spring docs", "1a", "[1000]", ""].map(isCitationMarker),
    [true, true, true, false, false, false, false]);
  const link = (label, href) => ({ textContent: label, getAttribute: () => href });
  const origin = "https://octryx.example";
  assert.equal(citationMarkerTarget(link("[1]", "https://wiki.example/page"), origin), "https://wiki.example/page");
  assert.equal(citationMarkerTarget(link("Spring docs", "https://wiki.example/page"), origin), null);
  assert.equal(citationMarkerTarget(link("2", "javascript:alert(1)"), origin), null, "unsafe links never open");
  const button = fs.readFileSync(path.join(SRC, "chat/evidence/AnswerSourcesButton.tsx"), "utf8");
  assert.match(button, /citationMarkerTarget/);
  assert.match(button, /answer-sources__item--focused/);
});

const group = (projectId, count) => ({ projectId, projectName: projectId, sessions: Array.from({ length: count }, (_, i) => ({ id: `${projectId}-${i}` })) });

test("the chat list follows the active Workspace; All workspaces is an explicit, remembered switch", () => {
  const { scopeThreadGroups, threadScopeProjectId, readAllWorkspaces, writeAllWorkspaces } = load("chat/threadScope.ts");
  const groups = [group("ws-a", 2), group("ws-b", 3), group("ws-c", 1)];
  const scoped = scopeThreadGroups(groups, "ws-b", false);
  assert.deepEqual([scoped.groups.map((g) => g.projectId), scoped.hiddenChats, scoped.hiddenWorkspaces, scoped.scoped],
    [["ws-b"], 3, 2, true]);
  assert.equal(scopeThreadGroups(groups, "ws-b", true).groups.length, 3);
  assert.equal(scopeThreadGroups(groups, "", false).groups.length, 3, "without an active Workspace nothing is hidden");
  assert.equal(threadScopeProjectId("ws-c", "ws-a"), "ws-c", "an opened chat of another Workspace shows its own list");
  assert.equal(threadScopeProjectId(null, "ws-a"), "ws-a");
  const memory = new Map();
  const store = { getItem: (key) => memory.get(key) ?? null, setItem: (key, value) => memory.set(key, value) };
  assert.equal(readAllWorkspaces(store, "u1"), false);
  writeAllWorkspaces(store, "u1", true);
  assert.equal(readAllWorkspaces(store, "u1"), true);
  assert.equal(readAllWorkspaces(store, "u2"), false, "per person");
  const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } };
  assert.equal(readAllWorkspaces(broken, "u1"), false);
  writeAllWorkspaces(broken, "u1", true);
});

test("the scope switch names what it shows and hides when nothing else exists", () => {
  const { ThreadScopeToggle } = load("chat/ThreadScopeToggle.tsx");
  const changes = [];
  const props = { allWorkspaces: false, hiddenChats: 4, hiddenWorkspaces: 2, workspaceName: "Petclinic", onChange: (v) => changes.push(v) };
  let view;
  act(() => { view = TestRenderer.create(createElement(ThreadScopeToggle, props)); });
  const button = view.root.findByProps({ "data-testid": "thread-scope-toggle" });
  assert.deepEqual([text(button), button.props["aria-pressed"]], ["All workspaces · 4 more chats", false]);
  act(() => button.props.onClick());
  assert.deepEqual(changes, [true]);
  act(() => view.update(createElement(ThreadScopeToggle, { ...props, allWorkspaces: true })));
  assert.equal(text(view.root.findByProps({ "data-testid": "thread-scope-toggle" })), "Only Petclinic");
  act(() => view.update(createElement(ThreadScopeToggle, { ...props, hiddenWorkspaces: 0 })));
  assert.equal(view.toJSON(), null);
  act(() => view.unmount());
  const shell = fs.readFileSync(path.join(SRC, "chat/SidebarShell.tsx"), "utf8");
  assert.match(shell, /useThreadScope\(chatState, searchedThreadGroups\)/);
});
