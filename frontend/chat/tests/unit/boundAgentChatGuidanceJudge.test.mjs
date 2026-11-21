// Independent rendered acceptance probes for. Product code is unchanged.
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
const { ComposerShell } = await import("../../src/chat/ComposerShell.tsx");
const { EmptyState } = await import("../../src/chat/EmptyState.tsx");

const noop = () => {};
function composer(overrides = {}) {
  return renderToStaticMarkup(createElement(ComposerShell, {
    selectedSession: { id: "thread-a", title: "Synthetic acceptance", status: "completed", agentId: "agent-a", agentName: "Cedar Assistant" },
    selectedSessionIsRunning: false,
    selectedAgentId: "agent-a", agentPillLabel: "Cedar Assistant",
    routingOverridesEnabled: false,
    chatAgentOptions: [], slashCommands: [], draftAttachments: [],
    runtimeOptions: [], projects: [], thinkingOptions: [], workflowOptions: [],
    slashCommand: { open: false, query: "" }, atMention: { open: false, query: "" },
    fileInputRef: { current: null }, textareaRef: { current: null },
    composerValue: "", selectedProjectId: "workspace-a", projectPillLabel: "Cedar",
    selectedWorkflowKey: "", workflowPillLabel: "Automatic", selectedRuntimeTargetId: "",
    runtimePillLabel: "Automatic", selectedThinkingLevel: "light", thinkingPillLabel: "Light",
    setSelectedWorkflowKey: noop, setSelectedRuntimeTargetId: noop,
    setSelectedProjectId: noop, setSelectedThinkingLevel: noop,
    ...overrides,
  }));
}

test("the bound agent remains visible after bootstrap disables editable routing overrides", () => {
  assert.match(composer(), />Cedar Assistant</);
});

test("an inherited binding has no misleading local clear-selection button", () => {
  assert.doesNotMatch(composer(), /aria-label="Clear selected agent"/);
});

test("an explicit unsent agent selection stays visible and can be cleared", () => {
  const html = composer({ selectedSession: null, routingOverridesEnabled: true });
  assert.match(html, />Cedar Assistant</);
  assert.match(html, /aria-label="Clear selected agent"/);
});

test("unknown capabilities do not advertise document or repository retrieval", () => {
  const html = renderToStaticMarkup(createElement(EmptyState, {
    projectName: "Cedar", projectId: "workspace-a", agentName: "Cedar Assistant", onUseStarter: noop,
  }));
  assert.doesNotMatch(html, />Ask the documents<|>Explain code with sources</);
});
