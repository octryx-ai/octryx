// Launch correction: from the "Test in chat" link through the real bootstrap hook to the real
// send body and the derived chat presentation. An agent shown for the next message must be the one
// the send carries; a requested agent that is not sent is only a notice.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { agentTestChatHref } from "../../src/admin/components/agentsTab/agentWorkspaceModel.ts";
import { useChatBootstrapState } from "../../src/chat/useChatBootstrapState.ts";
import { buildChatSendBody } from "../../src/chat/chatSendPayload.ts";
import { currentChatAgentGuidance, deriveChatAgentPresentation } from "../../src/chat/chatAgentGuidance.ts";
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

async function journey(agentId, serverState) {
  const search = new URL(agentTestChatHref(agentId, "w1"), "http://x").search;
  globalThis.window = { location: { search }, history: { replaceState() {} }, addEventListener() {}, removeEventListener() {} };
  globalThis.fetch = async (url) => ({
    ok: true, status: 200,
    json: async () => (String(url).includes("/bootstrap") ? serverState : { enabled: false }),
  });
  const sel = { project: "", agent: "", overrides: false, state: null };
  const set = (key) => (value) => { sel[key] = typeof value === "function" ? value(sel[key]) : value; };
  const noop = () => {};
  function Probe() {
    useChatBootstrapState({
      chatState: null, setChatState: set("state"),
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
  const body = buildChatSendBody("Hello", {
    sessionId: "", projectId: sel.project, runtimeTargetId: "", thinkingLevel: "light",
    routingOverridesEnabled: sel.overrides, agentId: sel.agent,
    workflowKey: "",
  });
  const presentation = deriveChatAgentPresentation({
    guidance: currentChatAgentGuidance(sel.state?.chatAgentGuidance, sel.state?.selectedSession ?? null),
    selectedSession: sel.state?.selectedSession ?? null, routingOverridesEnabled: sel.overrides,
    selectedAgentId: sel.agent, agentOptions: sel.state?.agentOptions ?? [],
  });
  return { body, presentation };
}

// Server state as `_build_chat_state(new_thread=True, agent_id=...)` projects it.
const server = (selectedAgentId, requested) => ({
  newThread: true, selectedSession: null, selectedProjectId: "w1", selectedAgentId,
  selectedAgentName: requested.name ?? "",
  agentOptions: [{ id: "a1", name: "Analytics" }], projects: [{ id: "w1", name: "Petclinic" }],
  currentUser: { roles: ["admin"] },
  chatAgentGuidance: {
    contractVersion: 1, sessionId: null, nextTurnAgent: requested, nextTurnAgentSource: "launch_request",
    lastTurnAgent: null, lastTurnSelectionSource: null, toolSurface: "unknown", contentSource: "unknown",
  },
});

const CASES = [
  ["inactive owned agent", "a9", "a9", { id: "a9", name: "Paused Agent", availability: "inactive" }, "inactive"],
  ["deleted or foreign agent", "a8", "", { id: "a8", name: null, availability: "unavailable" }, "unavailable"],
  ["active agent missing from the list", "a7", "a7", { id: "a7", name: "Hidden Agent", availability: "available" }, "not_in_list"],
];

for (const [label, id, selected, requested, reason] of CASES) {
  test(`${label}: not sent, not shown as the next agent, explained by a notice`, async () => {
    const { body, presentation } = await journey(id, server(selected, requested));
    assert.equal(body.agent_id, "");
    assert.equal(presentation.identity, null);
    assert.equal(presentation.unusedLaunchAgent.reason, reason);
    if (reason === "unavailable") assert.equal(presentation.unusedLaunchAgent.name, null);
  });
}

test("a selectable requested agent is sent and shown as the selected agent", async () => {
  const { body, presentation } = await journey("a1", server("a1", { id: "a1", name: "Analytics", availability: "available" }));
  assert.equal(body.agent_id, "a1");
  assert.deepEqual([presentation.identity.id, presentation.identity.role], [body.agent_id, "selected"]);
  assert.equal(presentation.unusedLaunchAgent, null);
});
