// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/newChatWorkspace.test.mjs
//
// Perf audit: "New chat" right after a login created the chat in an ARCHIVED project although Acme Orders
// was the selected Workspace. After a login the latest chat opens wherever it lives (also in an archived Workspace),
// and "New chat" took that chat's Workspace. Now it takes the active Workspace (the global switch).
import assert from "node:assert/strict";
import { test, beforeEach } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

function installWindow(href = "http://localhost/chat") {
  const target = new EventTarget();
  const store = new Map();
  const win = Object.assign(target, {
    location: new URL(href),
    history: { state: null, replaceState() {}, pushState() {} },
    localStorage: {
      getItem: (key) => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => store.set(key, String(value)),
      removeItem: (key) => store.delete(key),
    },
  });
  globalThis.window = win;
  return { win, store };
}

const { newChatWorkspaceId, useNewChatWorkspaceId } = await import("../../src/chat/useActiveWorkspace.ts");
const { setActiveWorkspaceUser, storeWorkspacePreference } = await import("../../src/chat/activeWorkspace.ts");
const { useThreadSidebarActions } = await import("../../src/chat/useThreadSidebarActions.ts");

// Active Workspaces only: the archived one ("legacy") is not in the list.
const PROJECTS = [{ id: "acme-orders" }, { id: "payments" }];

let env;
beforeEach(() => {
  env = installWindow();
  setActiveWorkspaceUser("u1");
});

test("a new chat starts in the active Workspace, not in the archived one of the chat on screen", () => {
  env.store.set("octryx-active-workspace:u1", "acme-orders");
  assert.equal(newChatWorkspaceId(PROJECTS, "legacy"), "acme-orders");
  assert.equal(newChatWorkspaceId(PROJECTS, "payments"), "acme-orders", "the global choice wins over the chat's");
});

test("without a choice: the chat's Workspace when active, else the default or the only one, else none", () => {
  assert.equal(newChatWorkspaceId(PROJECTS, "payments"), "payments");
  assert.equal(newChatWorkspaceId(PROJECTS, "legacy"), "", "several Workspaces and no default: nothing is guessed");
  assert.equal(newChatWorkspaceId([{ id: "acme-orders" }, { id: "payments", is_default: true }], "legacy"), "payments");
  assert.equal(newChatWorkspaceId([{ id: "acme-orders" }], "legacy"), "acme-orders");
  env.store.set("octryx-active-workspace:u1", "legacy");
  assert.equal(newChatWorkspaceId(PROJECTS, "legacy"), "", "a stored archived Workspace is never used");
});

test("an explicit no-workspace choice stays one where Global is allowed", () => {
  env.store.set("octryx-active-workspace:u1", "__none__");
  assert.equal(newChatWorkspaceId(PROJECTS, "payments", true), "");
  assert.equal(newChatWorkspaceId(PROJECTS, "payments", false), "payments");
});

test("New chat in the sidebar loads the draft of the active Workspace, also after a switch made elsewhere", async () => {
  const searches = [];
  let actions;
  let projectId;
  function Probe() {
    projectId = useNewChatWorkspaceId("u1", PROJECTS, "legacy");
    actions = useThreadSidebarActions({
      selectedSessionId: "s-latest", selectedProjectId: projectId, selectedRuntimeTargetId: "", canDeleteThreads: false,
      readJson: async () => ({}), loadState: async (search) => { searches.push(search); },
    });
    return null;
  }
  let view;
  act(() => { view = TestRenderer.create(createElement(Probe)); });
  try {
    act(() => storeWorkspacePreference("acme-orders"));
    assert.equal(projectId, "acme-orders", "the shell follows a choice made in another area");
    await act(async () => { await actions.handleNewThread(); });
    assert.equal(searches.length, 1);
    assert.equal(new URLSearchParams(searches[0]).get("project_id"), "acme-orders");
  } finally {
    act(() => view.unmount());
  }
});
