// The chat shows the agent bound for the next message, separates it from the latest turn, and
// derives starters/guidance only from the guidance of the displayed session and agent.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
      try { return nextResolve(`${specifier}.tsx`, context); } catch { /* Shared hook resolves pure TS. */ }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith(".css")) return { format: "module", source: "", shortCircuit: true };
    if (url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: transpileModule(readFileSync(new URL(url), "utf8"), {
      compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
    }).outputText };
    return nextLoad(url, context);
  },
});
const { currentChatAgentGuidance, deriveChatAgentPresentation } = await import("../../src/chat/chatAgentGuidance.ts");
const { mergeBootstrapState } = await import("../../src/chat/mergeChatState.ts");
const { EmptyState } = await import("../../src/chat/EmptyState.tsx");
const { WorkspacePrimaryContent } = await import("../../src/chat/WorkspacePrimaryContent.tsx");

const agentA = { id: "agent-a", name: "Cedar Assistant", availability: "available" };
const agentB = { id: "agent-b", name: "Birch Reviewer", availability: "available" };
const sessionA = { id: "thread-a", title: "A", status: "completed", agentId: "agent-b", agentName: "Birch Reviewer" };
const sessionB = { id: "thread-b", title: "B", status: "completed", agentId: "", agentName: "" };

function guidance(overrides = {}) {
  return {
    contractVersion: 1, sessionId: "thread-a", nextTurnAgent: agentA, nextTurnAgentSource: "session_binding",
    lastTurnAgent: agentB, lastTurnSelectionSource: "mention", toolSurface: "none", contentSource: "live_draft_row",
    ...overrides,
  };
}

function present(overrides = {}) {
  return deriveChatAgentPresentation({
    guidance: guidance(), selectedSession: sessionA, routingOverridesEnabled: false, selectedAgentId: "agent-b",
    agentOptions: [agentA, agentB], ...overrides,
  });
}

test("guidance applies only to the session it was projected for", () => {
  assert.equal(currentChatAgentGuidance(guidance(), sessionA).sessionId, "thread-a");
  assert.equal(currentChatAgentGuidance(guidance(), sessionB), null);
  assert.equal(currentChatAgentGuidance(guidance({ sessionId: null }), null).sessionId, null);
  assert.equal(currentChatAgentGuidance(undefined, sessionA), null);
  assert.equal(currentChatAgentGuidance(guidance({ contractVersion: 2 }), sessionA), null);
});

test("after a one-turn mention the bound agent stays next and the mention is the latest turn", () => {
  const { identity, toolSurface } = present();
  assert.deepEqual(
    [identity.id, identity.label, identity.role, identity.clearable, identity.latestTurnNote],
    ["agent-a", "Cedar Assistant", "bound", false, "Latest turn: Birch Reviewer"],
  );
  assert.equal(toolSurface, "none");
});

test("an unsent selection of another agent never inherits the bound agent's surface", () => {
  const other = present({ routingOverridesEnabled: true, selectedAgentId: "agent-b" });
  assert.deepEqual([other.identity.label, other.identity.role, other.identity.clearable], ["Birch Reviewer", "selected", true]);
  assert.equal(other.toolSurface, "unknown");
  const same = present({ routingOverridesEnabled: true, selectedAgentId: "agent-a" });
  assert.equal(same.toolSurface, "none");
  // Not in the catalog and no matched name: a generic label, never a stale one.
  const unknown = present({ routingOverridesEnabled: true, selectedAgentId: "agent-x", agentOptions: [] });
  assert.deepEqual([unknown.identity.label, unknown.identity.availability, unknown.toolSurface], ["Selected agent", "unknown", "unknown"]);
});

test("inactive and unavailable agents are labelled honestly and carry no surface", () => {
  const inactive = present({ guidance: guidance({ nextTurnAgent: { ...agentA, availability: "inactive" } }) });
  assert.deepEqual([inactive.identity.label, inactive.identity.availability, inactive.toolSurface], ["Cedar Assistant", "inactive", "unknown"]);
  const gone = present({ guidance: guidance({ nextTurnAgent: { id: "agent-z", name: null, availability: "unavailable" } }) });
  assert.deepEqual([gone.identity.label, gone.toolSurface], ["Agent unavailable", "unknown"]);
});

test("an unbound chat shows no agent; without guidance only a matching session record is shown", () => {
  assert.equal(present({ guidance: guidance({ nextTurnAgent: null }) }).identity, null);
  const legacy = present({ guidance: null });
  assert.deepEqual([legacy.identity.label, legacy.identity.role, legacy.identity.clearable, legacy.toolSurface], ["Birch Reviewer", "latest_turn", false, "unknown"]);
  assert.equal(present({ guidance: null, selectedAgentId: "agent-a" }).identity, null);
});

test("a response without guidance never keeps the previous session's guidance", () => {
  const previous = { selectedSession: sessionA, chatAgentGuidance: guidance() };
  assert.equal(mergeBootstrapState({ nextState: { selectedSession: sessionB }, previousState: previous }).chatAgentGuidance, null);
  const refreshed = mergeBootstrapState({ nextState: { selectedSession: sessionA, chatAgentGuidance: guidance({ toolSurface: "governed" }) }, previousState: previous });
  assert.equal(refreshed.chatAgentGuidance.toolSurface, "governed");
});

test("the empty chat offers pasted-text starters only and adapts its guidance to the surface", () => {
  const textOnly = renderToStaticMarkup(createElement(EmptyState, { projectName: "Cedar", projectId: "ws", agentName: "Cedar Assistant", agentAvailability: "available", toolSurface: "none", onUseStarter() {} }));
  assert.match(textOnly, /only with what you write in the chat/);
  assert.doesNotMatch(textOnly, /Add documents in Knowledge|documents, repositories and connected tools, where/);
  assert.match(textOnly, /Summarize pasted text/);
  const governed = renderToStaticMarkup(createElement(EmptyState, { projectName: "Cedar", projectId: "ws", toolSurface: "governed", onUseStarter() {} }));
  assert.doesNotMatch(governed, /Ask the documents|Explain code with sources|each answer/);
  assert.match(governed, /Add documents in Knowledge/);
  const inactive = renderToStaticMarkup(createElement(EmptyState, { projectName: "Cedar", agentName: "Cedar Assistant", agentAvailability: "inactive", onUseStarter() {} }));
  assert.match(inactive, /Cedar Assistant is inactive/);
  assert.doesNotMatch(inactive, /role="group"/);
  const gone = renderToStaticMarkup(createElement(EmptyState, { projectName: "Cedar", agentAvailability: "unavailable", onUseStarter() {} }));
  assert.match(gone, /no longer available to you/);
  assert.doesNotMatch(gone, /role="group"/);
});

const noop = () => {};
function primary({ chatState, selectedSession, ...overrides }) {
  return renderToStaticMarkup(createElement(WorkspacePrimaryContent, {
    chatState, selectedSession, selectedSessionIsRunning: false, displayTimeline: [], timelineFollowKey: "k",
    projectPillLabel: "Cedar", selectedProjectId: "ws", agentName: "", agentPillLabel: "Auto agent",
    referencedArtifactsByMessageId: new Map(), assistantRetryPromptByMessageId: new Map(), approvalRetryPromptById: new Map(),
    routingOverridesEnabled: false, selectedAgentId: "", filteredAgentOptions: [], agentGroups: [], SLASH_COMMANDS: [],
    slashCommand: { open: false, query: "" }, atMention: { open: false, query: "" }, draftAttachments: [],
    fileInputRef: { current: null }, textareaRef: { current: null }, composerValue: "", THINKING_OPTIONS: [], workflowOptions: [],
    selectedWorkflowKey: "", workflowPillLabel: "Automatic", selectedRuntimeTargetId: "", runtimePillLabel: "Automatic",
    selectedThinkingLevel: "light", thinkingPillLabel: "Light",
    setSelectedWorkflowKey: noop, setSelectedRuntimeTargetId: noop, setSelectedProjectId: noop, setSelectedThinkingLevel: noop,
    setComposerValue: noop, setRoutingOverridesEnabled: noop, setSelectedAgentId: noop,
    setSelectedAgentGroupId: noop, handleAgentGroupChange: noop, ...overrides,
  }));
}

test("the rendered chat shows the bound agent, the latest turn and text-only guidance for its session", () => {
  const html = primary({ chatState: { selectedSession: sessionA, chatAgentGuidance: guidance(), agentOptions: [] }, selectedSession: sessionA, selectedAgentId: "agent-b" });
  assert.match(html, /composer-agent-chip__label">Cedar Assistant</);
  assert.match(html, /Latest turn: Birch Reviewer/);
  assert.doesNotMatch(html, /Clear selected agent/);
  // An existing chat without messages is one line, not the welcome screen; the text-only hint stays.
  assert.match(html, /No messages yet\. This agent works only with what you write in the chat/);
  assert.doesNotMatch(html, /What can I help you with/);
});

test("switching to another session never shows the previous session's agent or surface", () => {
  // Session B is displayed while A's guidance is still in state (e.g. before the switch response).
  const html = primary({ chatState: { selectedSession: sessionB, chatAgentGuidance: guidance(), agentOptions: [] }, selectedSession: sessionB, agentName: "Cedar Assistant", agentPillLabel: "Cedar Assistant" });
  assert.doesNotMatch(html, /Cedar Assistant|composer-agent-chip/);
  assert.doesNotMatch(html, /only with what you write in the chat/);
});

// Root launch correction freeze: a requested agent ("Test in chat") is not a binding.
const { unusedLaunchAgentNotice } = await import("../../src/chat/chatOnboarding.ts");
const launch = (agent) => guidance({ sessionId: null, nextTurnAgent: agent, nextTurnAgentSource: "launch_request", lastTurnAgent: null, lastTurnSelectionSource: null, toolSurface: "unknown" });
const presentLaunch = (agent, overrides = {}) => present({ guidance: launch(agent), selectedSession: null, selectedAgentId: "", ...overrides });

test("a requested agent that is not sent gets no chip and a reasoned notice", () => {
  const inactive = presentLaunch({ id: "a9", name: "Paused Agent", availability: "inactive" });
  assert.equal(inactive.identity, null);
  assert.deepEqual(inactive.unusedLaunchAgent, { id: "a9", name: "Paused Agent", reason: "inactive" });
  const gone = presentLaunch({ id: "a8", name: null, availability: "unavailable" });
  assert.deepEqual(gone.unusedLaunchAgent, { id: "a8", name: null, reason: "unavailable" });
  const hidden = presentLaunch({ id: "a7", name: "Hidden Agent", availability: "available" });
  assert.deepEqual([hidden.identity, hidden.unusedLaunchAgent.reason], [null, "not_in_list"]);
  // Listed but cleared from the selection: not sent, so not shown as the next agent either.
  const cleared = presentLaunch(agentA);
  assert.deepEqual([cleared.identity, cleared.unusedLaunchAgent.reason], [null, "not_selected"]);
});

test("selecting the requested or another agent replaces the notice; bound sessions never get it", () => {
  const sent = presentLaunch(agentA, { routingOverridesEnabled: true, selectedAgentId: "agent-a" });
  assert.deepEqual([sent.identity.label, sent.identity.role, sent.unusedLaunchAgent], ["Cedar Assistant", "selected", null]);
  const other = presentLaunch({ id: "a9", name: "Paused Agent", availability: "inactive" }, { routingOverridesEnabled: true, selectedAgentId: "agent-b" });
  assert.deepEqual([other.identity.label, other.unusedLaunchAgent], ["Birch Reviewer", null]);
  assert.equal(present().unusedLaunchAgent, null);
});

test("the notice names the true reason and what sending does, never a foreign name", () => {
  assert.match(unusedLaunchAgentNotice({ name: "Paused Agent", reason: "inactive" }), /^Paused Agent is inactive, so it is not selected for this chat\. Sending uses this workspace's standard routing\.$/);
  const hidden = unusedLaunchAgentNotice({ name: "Hidden Agent", reason: "not_in_list" });
  assert.match(hidden, /not in this workspace's agent list/);
  assert.doesNotMatch(hidden, /inactive/);
  assert.match(unusedLaunchAgentNotice({ name: null, reason: "unavailable" }), /^The requested agent is not available to you/);
});

test("the rendered composer keeps the notice above the input with an Agents recovery link", () => {
  const inactive = primary({ chatState: { selectedSession: null, chatAgentGuidance: launch({ id: "a9", name: "Paused Agent", availability: "inactive" }), agentOptions: [] }, selectedSession: null, selectedAgentId: "a9", agentName: "Paused Agent", agentPillLabel: "Paused Agent", composerValue: "draft in progress" });
  assert.match(inactive, /Agent not selected/);
  assert.match(inactive, /Paused Agent is inactive, so it is not selected for this chat\. Sending uses this workspace&#x27;s standard routing\./);
  assert.match(inactive, /href="\/chat\?area=workflows&amp;tab=agents&amp;agent_id=a9">Open Agents/);
  assert.doesNotMatch(inactive, /composer-agent-chip/);
  assert.doesNotMatch(inactive, /Agent: Paused Agent/);
  const gone = primary({ chatState: { selectedSession: null, chatAgentGuidance: launch({ id: "a8", name: null, availability: "unavailable" }), agentOptions: [] }, selectedSession: null });
  assert.match(gone, /href="\/chat\?area=workflows&amp;tab=agents">Open Agents/);
  assert.doesNotMatch(gone, /a8|composer-agent-chip/);
  const chosen = primary({ chatState: { selectedSession: null, chatAgentGuidance: launch({ id: "a9", name: "Paused Agent", availability: "inactive" }), agentOptions: [agentB] }, selectedSession: null, routingOverridesEnabled: true, selectedAgentId: "agent-b" });
  assert.doesNotMatch(chosen, /Agent not selected/);
  assert.match(chosen, /composer-agent-chip__label">Birch Reviewer</);
});
