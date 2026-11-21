// Judge J-E-005: from the agent page's "Test in chat" link, through the real chat
// bootstrap hook, to the actual send body — the tested agent must arrive.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { agentTestChatHref } from "../../src/admin/components/agentsTab/agentWorkspaceModel.ts";
import { useChatBootstrapState } from "../../src/chat/useChatBootstrapState.ts";
import { buildChatSendBody } from "../../src/chat/chatSendPayload.ts";
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

async function bootstrap(search, serverState) {
  globalThis.window = {
    location: { search },
    history: { replaceState() {} },
    addEventListener() {},
    removeEventListener() {},
  };
  globalThis.fetch = async (url) => ({
    ok: true,
    status: 200,
    json: async () => (String(url).includes("/bootstrap") ? serverState : { enabled: false }),
  });
  const selection = { project: "", agent: "", overrides: false };
  const set = (key) => (value) => { selection[key] = typeof value === "function" ? value(selection[key]) : value; };
  const noop = () => {};
  function Probe() {
    useChatBootstrapState({
      chatState: null, setChatState: noop,
      setSelectedProjectId: set("project"), setSelectedRuntimeTargetId: noop, setSelectedThinkingLevel: noop,
      setSelectedAgentGroupId: noop, setSelectedAgentId: set("agent"),
      setSelectedModeKey: noop, setRoutingOverridesEnabled: set("overrides"), setRenameValue: noop, setError: noop,
      setLoading: noop, setSending: noop, setPendingPrompt: noop, setRenameOpen: noop, setSidebarOpen: noop,
      setStatsOpen: noop, setTaskErrorOpen: noop, setBulkMode: noop, setBulkSelectedThreadIds: noop,
      setTraceOpen: noop, setTtsEnabled: noop,
    });
    return null;
  }
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Probe)); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  act(() => view.unmount());
  return buildChatSendBody("Hello", {
    sessionId: "", projectId: selection.project, runtimeTargetId: "", thinkingLevel: "light",
    routingOverridesEnabled: selection.overrides, agentId: selection.agent,
    workflowKey: "",
  });
}

const server = (selectedAgentId, extra = {}) => ({
  newThread: true, selectedSession: null, selectedProjectId: "w1", selectedAgentId,
  agentOptions: [{ id: "a1", name: "Analytics" }],
  projects: [{ id: "w1", name: "Petclinic" }], currentUser: { roles: ["admin"] }, ...extra,
});

test("Test in chat sends the tested agent in its workspace and nothing retired", async () => {
  const href = agentTestChatHref("a1", "w1");
  const body = await bootstrap(new URL(href, "http://x").search, server("a1"));
  assert.equal(body.agent_id, "a1");
  assert.equal(body.project_id, "w1");
  assert.deepEqual(Object.keys(body).filter((key) => !["prompt", "session_id", "project_id", "runtime_target_id", "workflow_key", "thinking_level", "agent_id"].includes(key)), []);
});

test("a workspace default agent in a plain new chat is not sent as an explicit choice", async () => {
  const body = await bootstrap("?new=true&project_id=w1", server("a1"));
  assert.equal(body.agent_id, "");
});

test("an agent that is not a selectable option (e.g. inactive) is not sent", async () => {
  const body = await bootstrap("?new=true&agent_id=a9&project_id=w1&workspace_id=w1", server("a9"));
  assert.equal(body.agent_id, "");
});
