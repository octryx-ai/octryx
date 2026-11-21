// Switching chats reads only the session view, not the whole bootstrap (backend).
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { useChatBootstrapState } from "../../src/chat/useChatBootstrapState.ts";
import { sessionSwitchTarget, viewToState } from "../../src/chat/sessionView.ts";
import { chatNotFoundNotice, CHAT_NOT_FOUND_TEXT } from "../../src/chat/chatNotFound.ts";
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const previous = {
  newThread: true,
  selectedSession: null,
  selectedMessages: [],
  activeThreadGroups: [{ projectId: "w1", projectName: "Test", sessions: [
    { id: "s1", threadNumber: 3, title: "First" }, { id: "s2", threadNumber: 7, title: "Second" },
  ] }],
  archivedThreads: [], archivedThreadCount: 0,
  projects: [{ id: "w1", name: "Test" }],
  agentOptions: [{ id: "a1", name: "Engineer" }],
  branding: { app_name: "Octryx AI" },
  selectedWorkspace: { id: "w1", name: "Test" },
  currentUser: { roles: ["admin"] },
};

const view = (id, extra = {}) => ({
  requestedSessionNotFound: false,
  selectedSession: { id, threadNumber: 0, title: `Chat ${id}`, status: "idle" },
  selectedSessionIsArchived: false, selectedSessionIsRunning: false,
  selectedMessages: [{ id: `${id}-m1`, role: "user", content: "Hi" }], selectedMessagesHasMore: false,
  selectedProjectId: "w1", selectedWorkspace: null, chatAgentGuidance: null,
  ...extra,
});

async function switchChat(search, respond) {
  const calls = [];
  let state = previous;
  let load;
  globalThis.window = {
    location: { search: "" },
    history: { replaceState() {}, pushState() {} },
    addEventListener() {}, removeEventListener() {},
    localStorage: { getItem: () => null },
  };
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    return respond(String(url));
  };
  const noop = () => {};
  function Probe() {
    const result = useChatBootstrapState({
      chatState: previous, setChatState: (value) => { state = typeof value === "function" ? value(state) : value; },
      setSelectedProjectId: noop, setSelectedRuntimeTargetId: noop, setSelectedThinkingLevel: noop,
      setSelectedAgentGroupId: noop, setSelectedAgentId: noop, setSelectedModeKey: noop,
      setRoutingOverridesEnabled: noop, setRenameValue: noop, setError: noop, setLoading: noop, setSending: noop,
      setPendingPrompt: noop, setRenameOpen: noop, setSidebarOpen: noop, setStatsOpen: noop, setTaskErrorOpen: noop,
      setTraceOpen: noop, setTtsEnabled: noop,
    });
    load = result.loadState;
    return null;
  }
  let renderer;
  await act(async () => { renderer = TestRenderer.create(createElement(Probe)); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  calls.length = 0;
  state = previous;
  await act(async () => { await load(search, { preserveTrace: true }); });
  act(() => renderer.unmount());
  return { calls, state };
}

const ok = (body) => ({ ok: true, status: 200, json: async () => body });

test("only a plain ?session_id= address is a switch", () => {
  assert.equal(sessionSwitchTarget("?session_id=s2"), "s2");
  assert.equal(sessionSwitchTarget("?session_id=s2&new=true"), null);
  assert.equal(sessionSwitchTarget("?new=true&project_id=w1"), null);
  assert.equal(sessionSwitchTarget(""), null);
});

test("a switch reads the session view, not the bootstrap, and keeps the lists", async () => {
  const { calls, state } = await switchChat("?session_id=s2", (url) =>
    url.includes("/sessions/s2/view") ? ok(view("s2")) : ok({ enabled: false }));
  assert.equal(calls.filter((url) => url.includes("/bootstrap")).length, 0, "no bootstrap on a switch");
  assert.ok(calls.some((url) => url.includes("/chat/api/sessions/s2/view")));
  assert.equal(state.selectedSession.id, "s2");
  assert.equal(state.selectedSession.threadNumber, 7, "thread number from the list, not the view's 0");
  assert.equal(state.selectedMessages[0].id, "s2-m1");
  assert.equal(state.activeThreadGroups[0].sessions.length, 2, "the thread list stays");
  assert.deepEqual(state.projects, previous.projects);
  assert.deepEqual(state.agentOptions, previous.agentOptions);
  assert.deepEqual(state.branding, previous.branding);
  assert.deepEqual(state.selectedWorkspace, previous.selectedWorkspace, "a null Workspace keeps the current one");
  assert.equal(state.newThread, false);
});

test("a server without the view (404) falls back to the full bootstrap", async () => {
  const { calls, state } = await switchChat("?session_id=s2", (url) => {
    if (url.includes("/view")) return { ok: false, status: 404, json: async () => ({ detail: "Not Found" }) };
    if (url.includes("/bootstrap")) return ok({ ...previous, newThread: false, selectedSession: { id: "s2", threadNumber: 7, title: "Second" } });
    return ok({ enabled: false });
  });
  assert.ok(calls.some((url) => url.includes("/bootstrap?session_id=s2")));
  assert.equal(state.selectedSession.id, "s2");
});

test("a failing view read also falls back to the bootstrap", async () => {
  const { calls } = await switchChat("?session_id=s2", (url) => {
    if (url.includes("/view")) throw new Error("network");
    return ok({ ...previous, newThread: false, selectedSession: { id: "s2", title: "Second" } });
  });
  assert.ok(calls.some((url) => url.includes("/bootstrap")));
});

test("a missing or foreign chat keeps the list and says Chat not found", async () => {
  const { state } = await switchChat("?session_id=gone", (url) =>
    url.includes("/view")
      ? ok({ requestedSessionNotFound: true, selectedSession: null, selectedMessages: [], selectedWorkspace: null })
      : ok({ enabled: false }));
  assert.equal(state.selectedSession, null);
  assert.equal(state.activeThreadGroups[0].sessions.length, 2);
  assert.equal(chatNotFoundNotice(state), CHAT_NOT_FOUND_TEXT);
});

test("viewToState keeps a positive thread number from the view", () => {
  const next = viewToState(view("s9", { selectedSession: { id: "s9", threadNumber: 12, title: "x" } }), previous);
  assert.equal(next.selectedSession.threadNumber, 12);
});
