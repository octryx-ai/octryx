// No duplicate threads: a synchronous send lock,
// one idempotency key per draft message, latest-wins state loading, and one draft for "New chat".
import assert from "node:assert/strict";
import { test } from "node:test";

import { createSendGuard } from "../../src/chat/chatSendGuard.ts";
import {
  beginStateLoad,
  createStateLoadSequence,
  isLatestStateLoad,
  supersedeStateLoads,
} from "../../src/chat/stateLoadSequence.ts";
import { useMessageSend } from "../../src/chat/useMessageSend.ts";
import { useThreadSidebarActions } from "../../src/chat/useThreadSidebarActions.ts";

function installBrowser({ search = "", respond }) {
  const posts = [];
  const storage = new Map();
  globalThis.window = {
    location: { search },
    history: {
      pushState(_state, _title, url) {
        globalThis.window.location.search = new URL(url, "http://x").search;
      },
      replaceState(_state, _title, url) {
        globalThis.window.location.search = new URL(url, "http://x").search;
      },
    },
    localStorage: {
      getItem: (key) => storage.get(key) ?? null,
      setItem: (key, value) => storage.set(key, value),
      removeItem: (key) => storage.delete(key),
    },
  };
  globalThis.fetch = async (url, init) => {
    posts.push({ url: String(url), body: init?.body ? JSON.parse(init.body) : null });
    return respond(posts.length);
  };
  return posts;
}

const ok = (payload) => ({ ok: true, status: 200, statusText: "OK", json: async () => payload });
const fail = () => ({ ok: false, status: 502, statusText: "Bad Gateway", json: async () => ({ detail: "down" }) });

function sender({ sendGuard, applied = [] }) {
  const noop = () => {};
  return useMessageSend({
    composerValue: "Plan the hiring pipeline",
    setComposerValue: noop,
    draftAttachments: [],
    setDraftAttachments: noop,
    editingMessage: null,
    setEditingMessage: noop,
    selectedSession: null,
    selectedProjectId: "p1",
    selectedRuntimeTargetId: "",
    selectedThinkingLevel: "light",
    selectedAgentId: "",
    selectedWorkflowKey: "",
    routingOverridesEnabled: false,
    // The render closure still says "not sending" for the second Enter.
    sending: false,
    setSending: noop,
    setPendingPrompt: noop,
    setError: noop,
    setGenerateTaskResult: noop,
    composerHistory: [],
    setComposerHistory: noop,
    setComposerHistoryIndex: noop,
    composerNavigationDraftRef: { current: "" },
    composerDraftKey: "draft",
    chatHistoryStorageKey: "history",
    applyState: (state) => applied.push(state),
    sendGuard,
  });
}

test("double Enter in a new chat sends once, with one idempotency key", async () => {
  let release;
  const posts = installBrowser({
    respond: () =>
      new Promise((resolve) => {
        release = () => resolve(ok({ selectedSession: { id: "s1" } }));
      }),
  });
  const sendGuard = createSendGuard();
  const { handleSend } = sender({ sendGuard });

  const first = handleSend();
  const second = handleSend();
  await new Promise((resolve) => setImmediate(resolve));
  release();
  await Promise.all([first, second]);

  assert.equal(posts.length, 1);
  assert.equal(posts[0].body.session_id, "");
  assert.equal(typeof posts[0].body.idempotency_key, "string");
  assert.ok(posts[0].body.idempotency_key.length > 8);
});

test("a failed send keeps its key for the retry; a delivered one frees it", async () => {
  let attempt = 0;
  const posts = installBrowser({
    respond: () => {
      attempt += 1;
      return attempt === 1 ? fail() : ok({ selectedSession: { id: "s1" } });
    },
  });
  const sendGuard = createSendGuard();
  const { handleSend } = sender({ sendGuard });

  await handleSend();
  await handleSend();
  await handleSend();

  assert.equal(posts.length, 3);
  assert.equal(posts[0].body.idempotency_key, posts[1].body.idempotency_key);
  assert.notEqual(posts[1].body.idempotency_key, posts[2].body.idempotency_key);
});

test("a stale ?new=1 answer arriving after the send acknowledgement is dropped", () => {
  const sequence = createStateLoadSequence();
  const newChatLoad = beginStateLoad(sequence);
  // The send acknowledgement is applied while "New chat" is still loading.
  supersedeStateLoads(sequence);

  assert.equal(isLatestStateLoad(sequence, newChatLoad), false);
  const refresh = beginStateLoad(sequence);
  assert.equal(isLatestStateLoad(sequence, refresh), true);
});

test("pressing New chat on the unsent draft returns to it instead of opening another", async () => {
  installBrowser({ respond: () => ok({}) });
  const loads = [];
  let focused = 0;
  const actions = useThreadSidebarActions({
    selectedSessionId: null,
    selectedProjectId: "p1",
    selectedRuntimeTargetId: "",
    canDeleteThreads: false,
    readJson: async () => ({}),
    loadState: async (search) => {
      loads.push(search);
    },
    focusComposer: () => {
      focused += 1;
    },
  });

  await actions.handleNewThread();
  await actions.handleNewThread();

  assert.deepEqual(loads, ["?new=true&project_id=p1"]);
  assert.equal(focused, 2);
});

test("inline rename saves in place and never opens the chat", async () => {
  const posts = installBrowser({ search: "?session_id=open-chat", respond: () => ok({}) });
  const loads = [];
  const actions = useThreadSidebarActions({
    selectedSessionId: "open-chat",
    selectedProjectId: "p1",
    selectedRuntimeTargetId: "",
    canDeleteThreads: false,
    readJson: async (url, init) => {
      posts.push({ url, body: JSON.parse(init.body) });
      return {};
    },
    loadState: async (search, options) => {
      loads.push({ search, silent: Boolean(options?.silent) });
    },
  });

  await actions.handleRenameThread({ id: "other", title: "Old" }, "  Budget review  ");
  await actions.handleRenameThread({ id: "other", title: "Same" }, "Same");

  assert.deepEqual(posts, [{ url: "/chat/api/sessions/other/rename", body: { title: "Budget review" } }]);
  assert.deepEqual(loads, [{ search: "?session_id=open-chat", silent: true }]);
  assert.equal(globalThis.window.location.search, "?session_id=open-chat");
});
