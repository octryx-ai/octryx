// Chat first use: the empty chat and the header name the selected workspace truthfully. The
// composer pill's "Project required" (no workspace, non-admin) was shown as if it were a workspace:
// "The assistant can use what Project required provides …".
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as onboarding from "../../src/chat/chatOnboarding.ts";
import * as runDetailsFacts from "../../src/chat/header/runDetailsFacts.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const text = (node) => (typeof node === "string" ? node : node.children.map(text).join(""));

function load(name, mocks) {
  const exports = {};
  const source = fs.readFileSync(new URL(`../../src/chat/${name}.tsx`, import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports,
    window: { open() {} },
    require: (path) => {
      const key = path.split("/").at(-1);
      return key in mocks ? mocks[key] : require(path);
    },
  });
  return exports;
}

test("no-workspace labels are never shown as a workspace name", () => {
  // Non-admin without a workspace: the pill label is "Project required" and no id is selected.
  for (const label of ["Project required", "No project", ""]) {
    const hint = onboarding.workspaceHint(label, "");
    assert.match(hint, /^No workspace is selected\. Choose one in the composer/);
    assert.doesNotMatch(hint, /Project required|No project|Global chats/);
  }
  // Admin without a workspace: Global, with the Global capability note.
  assert.match(onboarding.workspaceHint("Global", ""), /only capabilities allowed for Global chats/);
  // A selected workspace is named; a workspace literally called "Global" is still a workspace.
  assert.match(onboarding.workspaceHint("Petclinic", "ws-1"), /^The assistant can use what Petclinic provides/);
  assert.match(onboarding.workspaceHint("Global", "ws-g"), /^The assistant can use what Global provides/);
  // Selected but the name has not loaded yet: never "Project required".
  assert.match(onboarding.workspaceHint("Project required", "ws-1"), /^The assistant can use what this workspace provides/);
  // Callers without an id read the label.
  assert.match(onboarding.workspaceHint("Project required"), /^No workspace is selected/);
});

test("the header names the workspace plainly", () => {
  assert.equal(onboarding.headerWorkspaceLabel("Petclinic"), "Petclinic");
  assert.equal(onboarding.headerWorkspaceLabel("Global"), "Global");
  assert.equal(onboarding.headerWorkspaceLabel("Project required"), "No workspace selected");
  assert.equal(onboarding.headerWorkspaceLabel(""), "No workspace selected");
});

test("the empty chat explains the missing workspace, starters only fill, and the documents link keeps scope", () => {
  const { EmptyState } = load("EmptyState", { chatOnboarding: onboarding });
  const filled = [];
  let view;
  act(() => {
    view = TestRenderer.create(createElement(EmptyState, { projectName: "Project required", projectId: "", onUseStarter: (prompt) => filled.push(prompt) }));
  });
  assert.match(text(view.root), /No workspace is selected\. Choose one in the composer/);
  assert.doesNotMatch(text(view.root), /what Project required provides/);
  const starters = view.root.findByProps({ role: "group" }).findAllByType("button");
  assert.equal(starters.length, onboarding.CHAT_STARTERS.length);
  act(() => starters[0].props.onClick());
  // Filling is the only effect: the prompt goes to the composer callback; EmptyState has no send path.
  assert.deepEqual(filled, [onboarding.CHAT_STARTERS[0].prompt]);
  act(() => view.update(createElement(EmptyState, { projectName: "Petclinic", projectId: "ws-1", onUseStarter() {} })));
  assert.match(text(view.root), /what Petclinic provides/);
  const href = new URL(view.root.findByType("a").props.href, "http://x");
  assert.deepEqual([href.searchParams.get("area"), href.searchParams.get("tab"), href.searchParams.get("workspace_id")], ["knowledge", "knowledgeSources", "ws-1"]);
  act(() => view.unmount());
});

function renderHeader(props, executionTarget = { kind: "server" }) {
  const { WorkspaceHeader } = load("WorkspaceHeader", {
    executionTarget: { useExecutionTarget: () => executionTarget },
    modelNames: { readableModelName: (id) => (id === "claude-haiku-5-5" ? "Claude Haiku 5.5" : id) },
    chatOnboarding: onboarding,
    ChatShellIcons: { MenuIcon: () => null },
    WorkspaceHeaderActions: { WorkspaceHeaderActions: () => null },
    chatLayoutBreakpoints: { isCompactChatLayout: () => true },
    useChatLayoutMode: { useChatLayoutMode: () => "compact" },
    useRunThreadTitle: { useRunThreadTitle: () => null },
    AuditMark: { AuditMark: () => createElement("span", { "data-testid": "chat-audit-mark" }, "Audited") },
    thinkingSwitch: { thinkingLevelLabel: (level) => ({ off: "Off", light: "Quick", deep: "Thorough" })[level] ?? "Quick" },
    routingExplainability: { buildRoutingSummary: () => ({ label: "Route · standard", detail: "standard" }) },
    runDetailsFacts,
    myRoleModel: { roleHeaderText: () => "" },
    useMyRole: { useMyRole: () => null },
    useThreadTranscript: { useThreadTranscript: () => ({ available: false, open() {}, viewer: null }) },
    ThreadEngineBadge: { ThreadEngineBadge: () => null },
    useSessionPool: { useSessionPool: () => null },
  });
  let view;
  act(() => {
    view = TestRenderer.create(createElement(WorkspaceHeader, {
      selectedSession: null, selectedSessionProjectLabel: "Project required",
      selectedSessionRuntimePillLabel: "", runtimePillLabel: "Auto · AWS Bedrock / anthropic.claude-sonnet-4-5-20250929-v1:0",
      activeWorkflowChipLabel: "Workflow · Automatic", threadStatusLabel: "Active", statusLabel: "Ready", thinkingLabel: "light",
      sending: false, selectedSessionIsRunning: false, taskErrorSummary: "", taskErrorOpen: false, setTaskErrorOpen() {},
      onContinue() {}, chatTheme: "dark", setChatTheme() {}, statsOpen: false, setStatsOpen() {}, stats: null, codeIntelligence: null,
      traceEventCount: 0, onOpenTrace() {}, onOpenSidebar() {}, workspaceOpen: false, onToggleWorkspace() {}, ...props,
    }));
  });
  return view;
}

test("the header is calm: workspace and short runtime up front, technical facts in one Run details disclosure", () => {
  const view = renderHeader({});
  const context = view.root.findByProps({ className: "workspace__context-line" });
  // Design review: the Run details disclosure ends the same line.
  assert.ok(text(context).startsWith("No workspace selectedAuto · AWS BedrockAuditedRun details"), text(context));
  assert.equal(context.findAllByProps({ "data-testid": "chat-audit-mark" }).length, 1, "the audit lock sits in the header");
  const details = view.root.findAllByType("details");
  assert.equal(details.length, 1);
  const body = text(details[0]);
  assert.match(body, /Run details/);
  assert.match(body, /anthropic\.claude-sonnet-4-5/, "the full model id stays reachable in the disclosure");
  // Label and value in words, not chips in capitals ("ROUTE · DIAGNOSIS").
  const facts = Object.fromEntries(details[0].findAllByType("dt").map((dt) => [text(dt), text(dt.parent.findByType("dd"))]));
  assert.deepEqual(Object.keys(facts), ["Model", "Status", "Thinking", "Route", "Workflow"]);
  assert.equal(facts.Thinking, "Quick");
  assert.equal(facts.Route, "standard");
  assert.equal(facts.Workflow, "Automatic");
  act(() => view.unmount());
});

test("a run on a device names the device's model in the header, never the Workspace default", () => {
  const session = { selectedSession: { id: "s1", title: "CHEF-2" }, selectedSessionProjectLabel: "Kitchen helper",
    selectedSessionRuntimePillLabel: "Automatic · Gemma 4 (Frankfurt)" };
  const device = { kind: "device", deviceId: "d1", folder: "/kitchen-helper", profile: "seat" };
  const withModel = renderHeader(session, { ...device, model: "claude-haiku-5-5" });
  const model = withModel.root.findByProps({ className: "workspace__context-model" });
  assert.equal(text(model), "Claude Haiku 5.5");
  act(() => withModel.unmount());
  const noModel = renderHeader(session, device);
  assert.equal(noModel.root.findAllByProps({ className: "workspace__context-model" }).length, 0, "the device default is not guessed");
  assert.doesNotMatch(text(noModel.root), /Gemma/);
  act(() => noModel.unmount());
});

test("Run details names the model the answers came from, and the current selection apart", () => {
  const messages = [
    { id: "u1", role: "user", content: "q" },
    { id: "a1", role: "assistant", content: "a", runtimeLabel: "bedrock / anthropic.claude-haiku-5-5" },
    { id: "a2", role: "assistant", content: "b", runtimeLabel: "bedrock / anthropic.claude-haiku-5-5" },
  ];
  const view = renderHeader({
    selectedSession: { id: "s1", title: "Welche postgres version" }, selectedSessionProjectLabel: "Acme Orders",
    selectedSessionRuntimePillLabel: "Automatic · Gemma 4 (Frankfurt)", threadStatusLabel: "Active", statusLabel: "Done", messages,
  });
  const details = view.root.findByType("details");
  const facts = Object.fromEntries(details.findAllByType("dt").map((dt) => [text(dt), text(dt.parent.findByType("dd"))]));
  assert.equal(facts["Model used"], "bedrock / anthropic.claude-haiku-5-5", "once, although two answers used it");
  assert.equal(facts["Selected model"], "Automatic · Gemma 4 (Frankfurt)");
  assert.equal(facts.Status, "Done", "not \"Active · Done\"");
  const model = view.root.findByProps({ className: "workspace__context-model" });
  assert.equal(text(model), "Claude Haiku 5.5", "the header names the model that answered, in words");
  assert.equal(model.props.title, "Model used: bedrock / anthropic.claude-haiku-5-5");
  act(() => view.unmount());
});

test("run details facts: models used in order, provider / model fallbacks, readable status", () => {
  const { modelsUsed, lastModelUsed, runStatusText, withoutPrefix } = runDetailsFacts;
  const messages = [
    { role: "assistant", model: "gemma-4-31b", providerName: "litellm_gateway" },
    { role: "user", runtimeLabel: "ignored" },
    { role: "assistant", turnTrace: { provider: "bedrock", model: "claude-haiku" } },
    { role: "assistant", runtimeLabel: "litellm_gateway / gemma-4-31b" },
  ];
  assert.deepEqual(modelsUsed(messages), ["litellm_gateway / gemma-4-31b", "bedrock / claude-haiku"]);
  assert.equal(lastModelUsed(messages), "litellm_gateway / gemma-4-31b");
  assert.deepEqual(modelsUsed([{ role: "assistant", content: "" }]), []);
  assert.equal(runStatusText("Active", "Done"), "Done");
  assert.equal(runStatusText("Archived", "Done"), "Archived · Done");
  assert.equal(withoutPrefix("Route · Diagnosis", "Route"), "Diagnosis");
});

test("a long chat title stays readable when the compact header cuts it to one line", () => {
  const title = "Migration of the payment service from Spring Boot 3 to Spring Boot 4 with all open questions";
  const view = renderHeader({ selectedSession: { id: "s1", title }, selectedSessionProjectLabel: "Petclinic" });
  const heading = view.root.findByProps({ className: "workspace__title" });
  assert.equal(heading.props.title, title);
  assert.equal(text(view.root.findByProps({ className: "workspace__context-line" })).startsWith("Petclinic"), true);
  act(() => view.unmount());
  const fresh = renderHeader({});
  assert.equal(fresh.root.findByProps({ className: "workspace__title" }).props.title, undefined, "a new chat has no tooltip");
  act(() => fresh.unmount());
});
