// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/chatTurnRequests.test.mjs
//
// Perf audit chat turn: the reply was drawn only after a full `/chat/api/bootstrap?session_id=` reload
// (654 ms), and `workflow-runs/by-session` was read 4–5 times per turn. Now a refresh from the session stream
// reads the session view and draws the reply from it; the bootstrap follows once in the background when the turn has
// ended (chat list), and the run bar reloads on messages, approvals and turn start/end only.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { useChatBootstrapState } from "../../src/chat/useChatBootstrapState.ts";
import { runRefreshKey } from "../../src/chat/workflowRun/workflowRunModel.ts";
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const userMessage = { id: "m1", role: "user", content: "Hallo", toolEvents: [] };
const reply = { id: "m2", role: "assistant", content: "Hallo! Wie kann ich helfen?", toolEvents: [] };

const running = {
  newThread: false,
  selectedSession: { id: "s1", threadNumber: 4, title: "Hallo", status: "running", runStatus: "in_progress" },
  selectedSessionIsRunning: true,
  selectedMessages: [userMessage],
  selectedApprovals: [],
  activeThreadGroups: [{ projectId: "w1", projectName: "Acme Orders", sessions: [{ id: "s1", threadNumber: 4, title: "Hallo" }] }],
  archivedThreads: [], archivedThreadCount: 0,
  projects: [{ id: "w1", name: "Acme Orders" }],
  currentUser: { roles: [] },
};

const view = (isRunning, messages) => ({
  requestedSessionNotFound: false,
  selectedSession: { id: "s1", threadNumber: 0, title: "Hallo", status: isRunning ? "running" : "idle",
    runStatus: isRunning ? "in_progress" : "completed" },
  selectedSessionIsArchived: false, selectedSessionIsRunning: isRunning,
  selectedMessages: messages, selectedMessagesHasMore: false, selectedApprovals: [],
  selectedProjectId: "w1", selectedWorkspace: null, chatAgentGuidance: null,
});

const bootstrap = (messages) => ({
  ...view(false, messages),
  activeThreadGroups: [{ projectId: "w1", projectName: "Acme Orders",
    sessions: [{ id: "s1", threadNumber: 1, title: "Hallo", preview: "Hallo! Wie kann ich helfen?" }] }],
  archivedThreads: [], archivedThreadCount: 0, projects: [{ id: "w1", name: "Acme Orders" }],
});

const ok = (body) => ({ ok: true, status: 200, json: async () => body });

function deferred() {
  let resolve;
  const promise = new Promise((ok) => { resolve = ok; });
  return { promise, resolve };
}

// The hook with `chatState` following its own updates, like AppContainer; returns the requests and the states.
async function streamRefresh(start, respond) {
  const calls = [];
  const applied = [];
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
  let state = start;
  let renderer;
  let load;
  const noop = () => {};
  function Probe({ chatState }) {
    const result = useChatBootstrapState({
      chatState,
      setChatState: (value) => {
        state = typeof value === "function" ? value(state) : value;
        applied.push(state);
        renderer?.update(createElement(Probe, { chatState: state }));
      },
      setSelectedProjectId: noop, setSelectedRuntimeTargetId: noop, setSelectedThinkingLevel: noop,
      setSelectedAgentGroupId: noop, setSelectedAgentId: noop, setSelectedModeKey: noop,
      setRoutingOverridesEnabled: noop, setRenameValue: noop, setError: noop, setLoading: noop, setSending: noop,
      setPendingPrompt: noop, setRenameOpen: noop, setSidebarOpen: noop, setStatsOpen: noop, setTaskErrorOpen: noop,
      setTraceOpen: noop, setTtsEnabled: noop,
    });
    load = result.loadState;
    return null;
  }
  await act(async () => { renderer = TestRenderer.create(createElement(Probe, { chatState: start })); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  calls.length = 0;
  applied.length = 0;
  state = start;
  await act(async () => { renderer.update(createElement(Probe, { chatState: start })); });
  return {
    calls, applied, get state() { return state; },
    refresh: () => act(async () => { await load("?session_id=s1", { preserveTrace: true, silent: true, sessionOnly: true }); }),
    settle: () => act(async () => { for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); }),
    close: () => act(() => renderer.unmount()),
  };
}

test("the end of a turn draws the reply from the session view; the bootstrap follows in the background", async () => {
  const held = deferred();
  const probe = await streamRefresh(running, (url) => {
    if (url === "/chat/api/sessions/s1/view") return ok(view(false, [userMessage, reply]));
    if (url.startsWith("/chat/api/bootstrap")) return held.promise.then(() => ok(bootstrap([userMessage, reply])));
    return { ok: false, status: 404, json: async () => ({}) };
  });
  try {
    await probe.refresh();
    assert.deepEqual(probe.calls, ["/chat/api/sessions/s1/view", "/chat/api/bootstrap?session_id=s1"]);
    assert.equal(probe.state.selectedMessages.at(-1).content, "Hallo! Wie kann ich helfen?",
      "the reply is on screen while the bootstrap still runs");
    assert.equal(probe.state.selectedSessionIsRunning, false);
    assert.equal(probe.state.activeThreadGroups[0].sessions[0].preview, undefined, "the list is still the old one");
    held.resolve();
    await probe.settle();
    assert.equal(probe.state.activeThreadGroups[0].sessions[0].preview, "Hallo! Wie kann ich helfen?");
    assert.equal(probe.calls.length, 2, "one view, one bootstrap");
    await probe.refresh();
    assert.deepEqual(probe.calls.slice(2), ["/chat/api/sessions/s1/view"], "a later refresh of the idle chat reads the view only");
  } finally {
    probe.close();
  }
});

test("refreshes while the turn runs read only the session view", async () => {
  const probe = await streamRefresh(running, (url) => {
    if (url === "/chat/api/sessions/s1/view") return ok(view(true, [userMessage]));
    return ok(bootstrap([userMessage]));
  });
  try {
    await probe.refresh();
    await probe.refresh();
    await probe.settle();
    assert.deepEqual(probe.calls, ["/chat/api/sessions/s1/view", "/chat/api/sessions/s1/view"]);
  } finally {
    probe.close();
  }
});

test("a new chat that is not in the list yet gets the bootstrap once its turn has ended", async () => {
  const unlisted = { ...running, selectedSessionIsRunning: false, activeThreadGroups: [] };
  const probe = await streamRefresh(unlisted, (url) => {
    if (url === "/chat/api/sessions/s1/view") return ok(view(false, [userMessage, reply]));
    return ok(bootstrap([userMessage, reply]));
  });
  try {
    await probe.refresh();
    await probe.settle();
    assert.deepEqual(probe.calls, ["/chat/api/sessions/s1/view", "/chat/api/bootstrap?session_id=s1"]);
    assert.equal(probe.state.activeThreadGroups[0].sessions[0].id, "s1");
  } finally {
    probe.close();
  }
});

test("a server without the session view refreshes from the bootstrap", async () => {
  const probe = await streamRefresh(running, (url) => {
    if (url === "/chat/api/sessions/s1/view") return { ok: false, status: 404, json: async () => ({}) };
    return ok(bootstrap([userMessage, reply]));
  });
  try {
    await probe.refresh();
    await probe.settle();
    assert.deepEqual(probe.calls, ["/chat/api/sessions/s1/view", "/chat/api/bootstrap?session_id=s1"]);
    assert.equal(probe.state.selectedMessages.at(-1).id, "m2");
  } finally {
    probe.close();
  }
});

test("the run bar reloads twice per turn: when it starts and when it ends", () => {
  // The states a chat turn passes through (send acknowledgement, refreshes during the turn, the reply, the list
  // bootstrap). The live activity line is not part of the chat state, so it never changes the key.
  const before = { selectedMessages: [], selectedApprovals: [] };
  const turn = [
    [{ selectedMessages: [userMessage], selectedApprovals: [] }, true],
    [{ selectedMessages: [userMessage], selectedApprovals: [] }, true],
    [{ selectedMessages: [userMessage], selectedApprovals: [] }, true],
    [{ selectedMessages: [userMessage, reply], selectedApprovals: [] }, false],
    [{ selectedMessages: [userMessage, reply], selectedApprovals: [] }, false],
  ];
  const keys = [runRefreshKey(before, false), ...turn.map(([state, isRunning]) => runRefreshKey(state, isRunning))];
  const reloads = keys.slice(1).filter((key, index) => key !== keys[index]).length;
  assert.equal(reloads, 2);
  const waiting = runRefreshKey({ selectedMessages: [userMessage], selectedApprovals: [{ id: "a1", status: "pending" }] }, true);
  assert.notEqual(waiting, keys[1], "an approval that opens reloads the run");
  assert.equal(runRefreshKey(null, false), "0:::idle");
});
