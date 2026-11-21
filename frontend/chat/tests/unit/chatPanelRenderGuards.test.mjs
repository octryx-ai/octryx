// Render guards for chat panels (performance panel, thread bulk dialog and toast, workflow routing, Office sidecar,
// execution trace drawer): key text and structure stay the same when the components are split into smaller parts.
import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import { act, box, load, noop, render, text } from "./renderGuardHarness.mjs";

const require = createRequire(import.meta.url);
const byClass = (root, name) => root.findAll((node) => typeof node.type === "string"
  && typeof node.props?.className === "string" && node.props.className.split(" ").includes(name));
const byTestId = (root, id) => root.findAll((node) => typeof node.type === "string" && node.props["data-testid"] === id);

test("the open performance panel shows its summary, steps, attempts and code intelligence", async () => {
  const { MessagePerformancePanel } = load("chat/messageBubblePanels.tsx");
  const performance = {
    hasPerformance: true, summary: [{ label: "Total", value: "3 s" }],
    modelSteps: [{ label: "Plan", value: "1 s" }, { label: "Answer", value: "2 s" }],
    toolSteps: [{ id: "t1", label: "read", status: "ok", value: "5 ms" }],
    runtimeAttempts: [{ id: "a1", label: "seat", status: "failed", error: "limit", value: "" }],
    codeIntelligence: { hasData: true, repositoryBackends: { lsp: 2, grep: 1 }, rows: [{ label: "Symbols", value: "12" }] },
  };
  const view = await render(MessagePerformancePanel, { isUser: false, performanceOpen: true, performance, performanceUnavailable: true });
  const root = view.root;
  assert.deepEqual(byClass(root, "message-performance-panel__section-title").map(text),
    ["Model steps", "Tool steps", "Runtime attempts", "Code intelligence"]);
  assert.deepEqual(byClass(root, "message-performance-panel__list-item").map(text),
    ["Plan1 s", "Answer2 s", "read · ok5 ms", "seat · failed · limit—", "Effective repo backendslsp 2 · grep 1", "Symbols12"]);
  assert.equal(text(byClass(root, "message-performance-panel__stat")[0]), "Total3 s");
  assert.equal(text(byClass(root, "message-performance-panel__empty")[0]), "No performance metrics were captured for this response.");
  act(() => view.unmount());
});

test("the bulk dialog shows the breakdown, its notes and the confirm button; the toast offers Undo", async () => {
  const reactDom = require("react-dom");
  const portal = reactDom.createPortal;
  reactDom.createPortal = (node) => node;
  try {
    const icon = (name) => ({ [name]: () => createElement("i", { "data-icon": name }) });
    const { ThreadBulkOverlays } = load("chat/ThreadBulkControls.tsx", {
      ChatShellIcons: { ...icon("ArchiveIcon"), ...icon("TrashIcon") },
      threadSidebarIcons: { ...icon("CloseIcon"), ...icon("InfoIcon"), ...icon("UndoIcon"), ...icon("WarnIcon") },
    }, { document: { body: {}, activeElement: null } });
    const calls = [];
    const threadBulk = {
      dialog: { action: "delete", notLoaded: 3, error: "Partly failed", running: false,
        preview: { byProject: [{ projectId: "p1", projectName: "Alpha", count: 2 }, { projectId: "", projectName: "No Workspace", count: 1 }],
          affectedIds: ["a", "b", "c"], subChats: 1, running: 2 } },
      toast: { text: "Archived 3 chats", undoIds: ["a"], secondsLeft: 9 },
      closeDialog: () => calls.push("close"), confirmDialog: async () => calls.push("confirm"), undo: async () => calls.push("undo"),
    };
    const view = await render(ThreadBulkOverlays, { threadBulk });
    const root = view.root;
    assert.equal(text(root.findByProps({ id: "thread-bulk-dialog-title" })), "Delete 3 chats?");
    assert.equal(text(byClass(root, "thread-bulk-dialog__breakdown")[0]), "Alpha2No Workspace1Total3");
    assert.deepEqual(byClass(root, "thread-bulk-dialog__note").map(text), [
      "3 of them are not loaded in the list. The server resolves the selection as of the moment you chose “Select all”; chats created later are not included.",
      "Includes 1 sub-chat; it goes with its parent.",
      "2 running chats are stopped before deletion.",
      "Deleting removes messages, files and traces. This cannot be undone. Audit records stay.",
      "Partly failed",
    ]);
    assert.equal(byClass(root, "thread-bulk-dialog__note--danger").length, 2);
    const buttons = root.findAll((node) => node.type === "button");
    assert.deepEqual(buttons.map(text), ["Cancel", "Delete 3 chats", "Undo"]);
    assert.equal(buttons[1].props.className, "admin-panel__action-btn admin-panel__action-btn--danger-solid");
    act(() => buttons[1].props.onClick());
    act(() => buttons[2].props.onClick());
    act(() => root.findByProps({ className: "thread-bulk-dialog__backdrop" }).props.onClick({ target: 1, currentTarget: 1 }));
    assert.deepEqual(calls, ["confirm", "undo", "close"]);
    assert.equal(text(byClass(root, "thread-bulk-toast")[0]), "Archived 3 chatsUndo9s");
    await act(async () => view.update(createElement(ThreadBulkOverlays, { threadBulk: { ...threadBulk, toast: null,
      dialog: { action: "archive", notLoaded: 0, error: null, running: false, preview: null } } })));
    assert.equal(text(root.findByProps({ id: "thread-bulk-dialog-title" })), "Archive chats?");
    assert.equal(text(byClass(root, "thread-bulk-dialog__pending")[0]), "Checking the selection…");
    assert.equal(byClass(root, "thread-bulk-toast").length, 0);
    act(() => view.unmount());
  } finally {
    reactDom.createPortal = portal;
  }
});

test("the routing panel reads the trace and names the contract, policy and tools", async () => {
  const { TraceWorkflowRoutingPanel } = load("chat/traceWorkflowRoutingPanel.tsx", { traceUiComponents: { TraceValue: box("value") } });
  const trace = { contextSnapshot: { request_analysis: {
    workflow_routing_policy_resolution: { source: "db", status: "matched", policy_id: "pol", policy_version_id: "v2",
      matched_group_id: "g1", tool_policy: { allowlist: ["read", " "], denylist: ["rm"] }, safety_constraints: { a: 1 } },
    workflow_contract: { workflow_id: "wf", workflow_class: "strict", diagram_source: "db", diagram_detail: "v3" },
  } } };
  const view = await render(TraceWorkflowRoutingPanel, { trace });
  const root = view.root;
  assert.equal(text(byClass(root, "trace-routing__header")[0]),
    "Workflow RoutingA database-managed routing policy matched; the workflow contract used code fallback or enrichment.DB matched");
  assert.equal(byClass(root, "trace-routing__badge--matched").length, 1);
  assert.equal(text(root.findByType("dl")), "WorkflowwfstrictContract sourcecode_fallbackDiagram sourcedbv3Policypolv2Matched groupg1Sourcedb");
  assert.deepEqual(byClass(root, "trace-routing__tools").map(text), ["Allowed toolsread", "Denied toolsrm"]);
  assert.equal(root.findAllByProps({ "data-testid": "value" }).length, 1);
  await act(async () => view.update(createElement(TraceWorkflowRoutingPanel, { resolution: { fallback_reason: "No match" } })));
  assert.equal(text(byClass(root, "trace-routing__badge")[0]), "Fallback");
  assert.match(text(byClass(root, "trace-routing__copy")[0]), /^No match$/);
  await act(async () => view.update(createElement(TraceWorkflowRoutingPanel, { workflowContract: { workflow_contract_source: "db_routing_policy" } })));
  assert.equal(text(byClass(root, "trace-routing__badge")[0]), "DB contract");
  await act(async () => view.update(createElement(TraceWorkflowRoutingPanel, {})));
  assert.equal(view.toJSON(), null);
  act(() => view.unmount());
});

test("the Office sidecar shows type, mode, profile, path, summary and the draft action button", async () => {
  const { OfficeDetailsSidecar } = load("chat/artifactPreviewOfficeSidecar.tsx", {
    artifactPreviewUtils: { formatOfficeValue: (v) => `<${v}>`, officeTypeHint: (t) => `hint ${t}`, titleFromKey: (k) => k.toUpperCase() },
    artifactPreviewOfficePanels: { OfficeActionModeToggle: box("mode-toggle") },
  });
  const drafted = [];
  const view = await render(OfficeDetailsSidecar, {
    artifact: { path: "/out/a.docx" }, detectedFileType: "docx", isRenderedPreview: false, modeTitle: "Outline",
    summaryRows: [["pages", 3]], actions: [{ id: "x", label: "Shorten", description: "Make it short" }], actionMode: "draft",
    setActionMode: noop, actionModeDescription: "Drafts first", actionsError: "Busy", busyActionId: null,
    draftOfficeAction: async (id) => drafted.push(id),
  });
  const root = view.root;
  assert.deepEqual(byClass(root, "artifact-preview__sidecard").map(text), [
    "Document typeDOCX", "Current modeOutline", "Document profilehint docx", "Output path/out/a.docx", "Quick summaryPAGES<3>",
    "Suggested actionsDrafts firstBusyShortenMake it shortUse as draft",
  ]);
  assert.equal(root.findAllByProps({ "data-testid": "mode-toggle" }).length, 1);
  const buttons = root.findAll((node) => node.type === "button");
  assert.equal(buttons.length, 1);
  act(() => buttons[0].props.onClick());
  assert.deepEqual(drafted, ["x"]);
  act(() => view.unmount());
});

test("the trace drawer shows the diff, the setup link, routing, checks and the tool events", async () => {
  const { TraceDrawer } = load("chat/traceDrawer.tsx", {
    traceToolEventList: { ToolEventList: (p) => createElement("ul", { "data-testid": "events" }, p.events.length) },
    traceTurnDiffUi: { TraceTurnDiffSection: box("diff") }, traceWorkflowChecksPanel: { TraceWorkflowChecksPanel: box("checks") },
    traceWorkflowRoutingPanel: { TraceWorkflowRoutingPanel: box("routing") },
    effectiveSetupModel: { effectiveSetupSessionHref: (id) => `/setup/${id}` },
  }, { document: { activeElement: null, addEventListener: noop, removeEventListener: noop } });
  const props = { open: true, events: [{ id: 1 }], sessionId: "s1", turnDiff: { a: 1 }, onClose: noop, canInspectSetup: true };
  const view = await render(TraceDrawer, props);
  const root = view.root;
  const drawer = root.findByType("aside");
  assert.equal(drawer.props.className, "trace-drawer trace-drawer--open");
  assert.equal(drawer.props.role, "dialog");
  assert.equal(text(byClass(root, "trace-drawer__heading")[0]), "Last execution changesExecution trace");
  assert.deepEqual(byClass(root, "trace-drawer__section-title").map(text), ["Execution diff", "Tool events"]);
  assert.equal(byTestId(root, "trace-effective-setup-link")[0].props.href, "/setup/s1");
  for (const id of ["diff", "routing", "checks", "events"]) assert.equal(root.findAllByProps({ "data-testid": id }).length, 1, id);
  await act(async () => view.update(createElement(TraceDrawer, { ...props, open: false, events: [], turnDiff: null, canInspectSetup: false })));
  assert.equal(root.findByType("aside").props["aria-hidden"], true);
  assert.equal(text(byClass(root, "trace-empty")[0]), "No tool calls yet for this chat.");
  assert.deepEqual(byClass(root, "trace-drawer__section-title").map(text), ["Tool events"]);
  assert.equal(root.findAllByProps({ "data-testid": "checks" }).length, 0);
  act(() => view.unmount());
});
