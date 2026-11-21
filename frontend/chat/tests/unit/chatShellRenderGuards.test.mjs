// Render guards for the chat sidebar and message bubble: key text and structure stay the same when the
// components are split into smaller parts. Heavy children are stubbed by module name.
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

// Loads a source file (the stored "All workspaces" switch reads as on); relative imports resolve to a stub (by file name) or to the real .tsx/.ts file.
function load(relative, stubs = {}) {
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
      encodeURIComponent, setTimeout, clearTimeout,
      window: { localStorage: { getItem: () => "on", setItem() {} }, setTimeout, clearTimeout, open() {} },
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

function sidebarStubs() {
  return {
    ThreadGroupSection: {
      ThreadGroupSection: ({ group, searching, bulk, onDraftSelect }) => createElement("section", {
        "data-testid": "thread-group", "data-searching": String(searching), "data-bulk": String(Boolean(bulk)),
        "data-draft": String(Boolean(onDraftSelect)),
      }, group.projectName),
    },
    ThreadBulkControls: {
      ThreadBulkActionBar: box("bulk-bar"), ThreadBulkHeader: box("bulk-header"), ThreadBulkOverlays: () => null,
    },
    ThreadArchivedView: { ThreadArchivedView: box("archived-view") },
    ThreadSearchBox: { ThreadSearchBox: ({ value }) => createElement("input", { "data-testid": "search", value, readOnly: true }) },
    ThreadScopeToggle: { ThreadScopeToggle: box("scope-toggle") },
    ThreadHoverCard: { ThreadHoverCard: () => null },
    ThreadMarkerLegend: { ThreadMarkerLegend: box("legend") },
    ThreadDraftRow: { ThreadDraftRow: box("draft-row") },
  };
}

const thread = (id, title) => ({ id, title, status: "completed", updatedAt: "2026-11-20T10:00:00Z", createdAt: "2026-11-20T10:00:00Z" });

function renderSidebar(props = {}) {
  const { SidebarShell } = load("chat/SidebarShell.tsx", sidebarStubs());
  const groups = [
    { projectId: "p1", projectName: "Petclinic", sessions: [thread("t1", "One"), thread("t2", "Two")] },
    { projectId: "gone", projectName: "Old space", sessions: [thread("t3", "Three")] },
  ];
  const noop = () => {};
  const threadBulk = { bulkMode: false, enter: noop, archiveOne: noop, deleteOne: noop, selectAll: noop, restore: noop };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(SidebarShell, {
      chatState: { projects: [{ id: "p1", name: "Petclinic" }], archivedThreadCount: 4, selectedSession: { id: "t1" },
        selectedProjectId: "p1", dashboardUrl: "/home", currentUser: { id: "u1" } },
      filteredThreadGroups: groups, handleThreadSelect: noop, handleNewThread: async () => {},
      threadSearchQuery: "", setThreadSearchQuery: noop, threadBulk,
      onPinThread: noop, onRenameThread: noop, onArchiveThread: noop, onExportThread: noop, onExportAnalysisThread: noop,
      onDeleteThread: noop, onLoadThreadGroupPage: noop, collapsed: false, onToggleCollapsed: noop, ...props,
    }));
  });
  return view;
}

test("the sidebar renders its header, counts, active and other groups and the archived link", () => {
  const view = renderSidebar({ threadSearchQuery: "" });
  const root = view.root;
  assert.equal(root.findByType("aside").props.className, "sidebar");
  assert.equal(text(root.findByProps({ className: "brand__title" })), "Chats");
  assert.equal(root.findByProps({ className: "sidebar__collapse-btn" }).props["aria-label"], "Collapse chats");
  assert.equal(text(root.findByProps({ className: "sidebar__section-meta" })), "3 chats · 2 Workspaces");
  const buttons = root.findAllByProps({ className: "icon-button sidebar__icon-btn" }).map((button) => button.props["aria-label"]);
  assert.deepEqual(buttons, ["What the row markers mean", "Select chats", "New chat"]);
  assert.equal(root.findAllByProps({ "data-testid": "scope-toggle" }).length, 1);
  const groups = root.findAllByProps({ "data-testid": "thread-group" });
  assert.deepEqual(groups.map((group) => text(group)), ["Petclinic", "Old space"]);
  assert.match(text(root.findByType("summary")), /Other workspaces \(inactive or unavailable\) · 1 · 1 chat/);
  assert.equal(text(root.findByProps({ className: "sidebar__archived-link" })), "Archived chats4");
  assert.equal(root.findAllByProps({ "data-testid": "draft-row" }).length, 0);
  act(() => view.unmount());
});

test("the sidebar shows bulk header and bar in bulk mode and an empty search line", () => {
  const noop = () => {};
  const bulk = renderSidebar({ threadBulk: { bulkMode: true, selection: { ids: {}, scopes: {} }, query: "", searchOffers: {}, enter: noop, archiveOne: noop, deleteOne: noop, selectAll: noop, restore: noop } });
  assert.equal(bulk.root.findAllByProps({ "data-testid": "bulk-header" }).length, 1);
  assert.equal(bulk.root.findAllByProps({ "data-testid": "bulk-bar" }).length, 1);
  assert.equal(bulk.root.findAllByProps({ className: "sidebar__archived-link" }).length, 0);
  act(() => bulk.unmount());
  const empty = renderSidebar({ filteredThreadGroups: [], threadSearchQuery: "zzz", chatState: { projects: [], selectedSession: null, selectedProjectId: "p9" } });
  assert.equal(text(empty.root.findByProps({ className: "sidebar__empty" })), "No chat matches “zzz”.");
  assert.equal(empty.root.findAllByProps({ "data-testid": "draft-row" }).length, 1);
  act(() => empty.unmount());
});

function renderBubble(message, props = {}) {
  const { MessageBubble } = load("chat/MessageBubble.tsx", {
    messageBubbleContent: {
      MessageBubbleContent: (p) => createElement("div", {
        "data-testid": "bubble", "data-title": p.participantTitle, "data-support": p.participantSupportLabel,
        "data-user": String(p.isUser), "data-thinking": String(p.isThinking), "data-intermediate": String(p.intermediateToolStep),
      }, p.displayContent),
    },
    useTurnExecutionSummary: { useTurnExecutionSummary: () => ({ load: null, retry() {} }) },
  });
  const noop = () => {};
  let view;
  act(() => {
    view = TestRenderer.create(createElement(MessageBubble, {
      message, currentUserName: "Dana", feedbackDisabled: false, onSubmitFeedback: noop, onReuseMessage: noop,
      onEditMessage: noop, onRetryFromMessage: noop, onRetryFromToolEvent: noop, onRetryPrompt: noop,
      actionsDisabled: false, theme: "dark", ...props,
    }));
  });
  return view;
}

const msg = (fields) => ({ id: "m1", content: "Hello there", createdAt: "2026-11-20T10:00:00Z", toolEvents: [], ...fields });

test("a message bubble names its author and passes the content on", () => {
  const user = renderBubble(msg({ role: "user" }));
  const bubble = user.root.findByProps({ "data-testid": "bubble" });
  assert.deepEqual([bubble.props["data-title"], bubble.props["data-support"], bubble.props["data-user"]], ["Dana", "", "true"]);
  assert.equal(text(bubble), "Hello there");
  act(() => user.unmount());
  const answer = renderBubble(msg({ role: "assistant", model: "claude-haiku-5-5" }));
  const reply = answer.root.findByProps({ "data-testid": "bubble" });
  assert.equal(reply.props["data-support"], "Assistant");
  assert.equal(reply.props["data-intermediate"], "false");
  act(() => answer.unmount());
});

test("a platform turn is a quiet note from Octryx", () => {
  const view = renderBubble(msg({ role: "user", origin: "platform", content: "git merge" }));
  const note = view.root.findByProps({ "data-testid": "message-platform-note" });
  assert.equal(note.props.title, "git merge");
  assert.match(text(note), /^OctryxGit work for the run's items: worktrees and merges/);
  act(() => view.unmount());
});
