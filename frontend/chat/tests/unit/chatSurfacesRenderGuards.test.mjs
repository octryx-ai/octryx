// Render guards for chat surfaces (composer footer, turn diff summary, inline tool execution, workflow proposal
// options, decision card, device run policy, files panel): key text and structure stay the same when the components
// are split into smaller parts. Heavy children and network modules are stubbed by module name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, box, flush, load, noop, render, text } from "./renderGuardHarness.mjs";

const json = (value) => JSON.stringify(value);
const classes = (root, name) => root.findAll((node) => typeof node.props?.className === "string"
  && node.props.className.split(" ").includes(name) && typeof node.type === "string");

function composerFooter(target = "server") {
  return load("chat/ComposerFooterControls.tsx", {
    ChatShellIcons: { OptionsIcon: () => createElement("i", null, "opt"), SendIcon: () => createElement("i", null, "send"),
      StopIcon: () => createElement("i", null, "stop") },
    ComposerRoutingPills: { ComposerRoutingPills: (p) => createElement("div", { "data-testid": "pills", "data-hide": String(p.hideServerOnly) }, p.runOn) },
    RunOnControls: { RunOnControls: (p) => createElement("span", { "data-testid": "run-on" }, p.workspaceName) },
    executionTarget: { useExecutionTarget: () => ({ kind: target }) },
    ComposerUtilityActions: {
      ComposerAttachButton: box("attach"),
      ComposerUtilityActions: (p) => createElement("div", { "data-testid": "utility", "data-attach": String(p.showAttach) }),
    },
  }).ComposerFooterControls;
}

function footerProps(overrides = {}) {
  return {
    layoutMode: "desktop", composerDisabled: false, uploadingAttachments: false, fileInputRef: { current: null },
    runtimePillLabel: "Auto", selectedRuntimeTargetId: "", setSelectedRuntimeTargetId: noop, runtimeOptions: [],
    projectPillLabel: "Petclinic", selectedProjectId: "p1", selectedThinkingLevel: "light", setSelectedThinkingLevel: noop,
    workflowOptions: [], selectedWorkflowKey: "", setSelectedWorkflowKey: noop, workflowPillLabel: "Automatic",
    selectedWorkflowCapability: null, sttAvailable: false, sttListening: false, startSTT: noop, selectedSession: { id: "s1" },
    showCanvas: false, openCanvas: noop, ttsEnabled: true, selectedSessionIsRunning: false, selectedSessionIsArchived: false,
    sending: false, composerValue: "hi", draftAttachments: [], textareaRef: { current: null }, handleComposerChange: noop,
    handleStop: noop, handleSend: noop, ...overrides,
  };
}

test("the composer footer shows pills, utilities, send and the live hints on desktop", async () => {
  const ComposerFooterControls = composerFooter();
  const sent = [];
  const view = await render(ComposerFooterControls, footerProps({ selectedSessionIsRunning: true, handleStop: () => sent.push("stop") }));
  const root = view.root;
  assert.equal(root.findByProps({ className: "composer__footer" }).type, "div");
  assert.equal(root.findByProps({ "data-testid": "pills" }).props["data-hide"], "false");
  assert.equal(text(root.findByProps({ "data-testid": "run-on" })), "Petclinic");
  assert.equal(root.findByProps({ "data-testid": "utility" }).props["data-attach"], "true");
  const send = root.findByProps({ "aria-label": "Stop run" });
  assert.equal(send.props.className, "send-button send-button--stop");
  assert.equal(send.props.disabled, false);
  act(() => send.props.onClick());
  assert.deepEqual(sent, ["stop"]);
  assert.equal(text(root.findByProps({ className: "composer__hint-group composer__hint-group--status" })), "Voice enabled·Run active");
  act(() => view.update(createElement(ComposerFooterControls, footerProps({ ttsEnabled: false, composerValue: " " }))));
  assert.equal(root.findAllByProps({ className: "composer__hint-row" }).length, 0);
  assert.equal(root.findByProps({ "aria-label": "Send message" }).props.disabled, true);
  act(() => view.unmount());
});

test("the phone composer keeps attach and send outside the Options disclosure and remembers it", async () => {
  const ComposerFooterControls = composerFooter("device");
  const view = await render(ComposerFooterControls, footerProps({ layoutMode: "phone", sending: true }));
  const root = view.root;
  assert.equal(root.findByProps({ className: "composer__footer composer__footer--compact" }).type, "div");
  assert.equal(root.findAllByProps({ "data-testid": "attach" }).length, 1);
  assert.equal(root.findAllByProps({ "data-testid": "pills" }).length, 0);
  assert.equal(classes(root, "send-button__spinner").length, 1);
  const options = root.findByProps({ "aria-controls": "composer-compact-options" });
  assert.equal(options.props["aria-expanded"], false);
  act(() => options.props.onClick());
  const panel = root.findByProps({ id: "composer-compact-options" });
  assert.equal(panel.findByProps({ "data-testid": "pills" }).props["data-hide"], "true");
  assert.equal(panel.findByProps({ "data-testid": "utility" }).props["data-attach"], "false");
  act(() => view.update(createElement(ComposerFooterControls, footerProps({ layoutMode: "desktop" }))));
  act(() => view.update(createElement(ComposerFooterControls, footerProps({ layoutMode: "phone" }))));
  assert.equal(root.findAllByProps({ id: "composer-compact-options" }).length, 1, "the open disclosure survives a layout switch");
  act(() => view.unmount());
});

test("the turn diff summary shows counts, preview, overview and one row per command, file and policy event", async () => {
  const { TurnDiffSummary } = load("chat/turnDiffSummary.tsx");
  const opened = [];
  const turnDiff = {
    commands: [{ command: "npm test", cwd: "/app", status: "ok" }, { command: "ls" }],
    file_changes: [{ path: "a.ts", action: "created", details: "new" }, { path: "b.ts", action: "deleted" }, { path: "c.ts", action: "renamed" }],
    policy_events: [{ action: "deny", reason: "secret" }],
  };
  const view = await render(TurnDiffSummary, { turnDiff, onOpen: () => opened.push(1) });
  const root = view.root;
  assert.equal(root.findByType("details").props.className, "turn-diff-summary");
  const deltas = classes(root, "turn-diff-summary__delta").map((node) => text(node));
  assert.equal(json(deltas), json(["+1", "-1", "1 changed"]));
  assert.equal(json(classes(root, "turn-diff-summary__meta").map((node) => text(node))), json(["2 commands", "1 policy"]));
  assert.equal(json(classes(root, "turn-diff-summary__overview-label").map((node) => text(node))), json(["Command", "File", "Policy"]));
  assert.equal(json(classes(root, "turn-diff-summary__section-label").map((node) => text(node))), json(["Commands", "Files", "Policy"]));
  assert.equal(classes(root, "turn-diff-summary__row").length, 6);
  assert.equal(json(classes(root, "turn-diff-summary__row-subtle").map((node) => text(node))), json(["cwd /app", "new", "secret"]));
  assert.equal(json(classes(root, "trace-turn-diff__badge").map((node) => text(node))),
    json(["ok", "command", "created", "deleted", "renamed", "deny"]));
  const preview = classes(root, "turn-diff-summary__preview");
  assert.equal(preview.length, 1);
  const before = text(root.findByType("details"));
  act(() => root.findByProps({ className: "turn-diff-summary__open" }).props.onClick());
  assert.equal(opened.length, 1);
  act(() => view.update(createElement(TurnDiffSummary, { turnDiff: { commands: [{ command: "ls" }] } })));
  assert.equal(classes(root, "turn-diff-summary__footer").length, 0);
  assert.equal(classes(root, "turn-diff-summary__delta").length, 0);
  assert.equal(json(classes(root, "turn-diff-summary__meta").map((node) => text(node))), json(["1 command"]));
  act(() => view.update(createElement(TurnDiffSummary, { turnDiff: {} })));
  assert.equal(view.toJSON(), null);
  assert.equal(before, "Execution traceExecution diffnpm test · a.ts · new...+1-11 changed2 commands1 policyOpen>Command"
    + "npm testFilea.ts · newPolicysecretCommandsnpm testcwd /appoklscommandFilesa.tsnewcreatedb.tsdeletedc.tsrenamed"
    + "PolicysecretsecretdenyOpen trace");
  act(() => view.unmount());
});

function filesPanelProps(overrides = {}) {
  const entry = (relativePath, kind, depth, extra = {}) => ({
    relativePath, path: `/ws/${relativePath}`, name: relativePath.split("/").pop(), kind, depth, ...extra,
  });
  const childrenByParent = new Map([
    ["", [entry("src", "directory", 0), entry("README.md", "file", 0, { sizeBytes: 2048, url: "/f/readme" })]],
    ["src", [entry("src/a.ts", "file", 1, { url: "/f/a" })]],
  ]);
  return {
    displayedFiles: [1, 2, 3], searchLoading: false, searchError: null, loweredQuery: "", bulkMode: true,
    selectedEntries: [{}], selectedPaths: ["README.md"], selectedPreviewPath: "src/a.ts", childrenByParent,
    expandedPaths: {}, loadingDirectories: {}, onToggleSelection: noop, onToggleExpanded: noop, onSelectPreviewFile: noop,
    onOpenArtifact: noop, onRename: noop, onMove: noop, onDelete: noop, ...overrides,
  };
}

test("the working files panel shows the bulk bar, the nested tree and its empty states", async () => {
  const { WorkspaceFilesPanel } = load("chat/WorkspaceSidePanelFilesPanel.tsx");
  const calls = [];
  const view = await render(WorkspaceFilesPanel, filesPanelProps({
    onToggleExpanded: (path) => calls.push(["toggle", path]), onSelectPreviewFile: (entry) => calls.push(["preview", entry.name]),
    onToggleSelection: (path) => calls.push(["select", path]),
  }));
  const root = view.root;
  assert.equal(text(root.findByProps({ className: "workspace-sidepanel__bulkbar" }).findAllByType("span")[0]), "1 selected");
  const bulk = classes(root, "workspace-sidepanel__bulk-btn").map((node) => [text(node), node.props.disabled]);
  assert.equal(json(bulk), json([["Rename", false], ["Move", false], ["Delete", false]]));
  assert.equal(json(classes(root, "workspace-sidepanel__tree-name").map((node) => text(node))), json(["src", "a.ts", "README.md"]));
  assert.equal(classes(root, "workspace-sidepanel__tree-row--selected").length, 1);
  assert.equal(classes(root, "workspace-sidepanel__tree-row--preview-active").length, 1);
  assert.equal(json(classes(root, "workspace-sidepanel__tree-meta").map((node) => text(node))), json(["1 item", "2.0 KB"]));
  assert.equal(root.findAllByType("input").length, 3);
  const entries = classes(root, "workspace-sidepanel__tree-entry");
  act(() => entries[0].props.onClick());
  act(() => entries[2].props.onClick());
  act(() => root.findAllByType("input")[1].props.onChange());
  assert.equal(json(calls), json([["toggle", "src"], ["preview", "README.md"], ["select", "src/a.ts"]]));
  act(() => view.update(createElement(WorkspaceFilesPanel, filesPanelProps({ bulkMode: false, expandedPaths: { src: false } }))));
  assert.equal(classes(root, "workspace-sidepanel__bulkbar").length, 0);
  assert.equal(classes(root, "workspace-sidepanel__tree-check--spacer").length, 2);
  assert.equal(json(classes(root, "workspace-sidepanel__tree-name").map((node) => text(node))), json(["src", "README.md"]));
  act(() => view.update(createElement(WorkspaceFilesPanel, filesPanelProps({ displayedFiles: [], loweredQuery: "x" }))));
  assert.equal(text(root.findByProps({ className: "workspace-sidepanel__empty" })), "No working files match the current filter.");
  act(() => view.update(createElement(WorkspaceFilesPanel, filesPanelProps({ searchError: "Boom" }))));
  assert.equal(text(root.findByProps({ className: "workspace-sidepanel__empty" })), "Boom");
  act(() => view.unmount());
});

test("the phone chat header keeps error and trace inline and lists the rest in the menu, which stays open across widths", async () => {
  const { WorkspaceHeaderActions } = load("chat/header/WorkspaceHeaderActions.tsx", { StatsPopover: { StatsPopover: box("stats") } });
  const props = (layoutMode) => ({
    layoutMode, hasSelectedSession: true, taskError: "boom", taskErrorSummary: "Boom", taskErrorOpen: true, setTaskErrorOpen: noop,
    selectedSessionIsRunning: false, onContinue: noop, workspaceOpen: true, onToggleWorkspace: noop, onExportEvidencePdf: noop,
    onExportAnalysisJson: noop, chatTheme: "light", setChatTheme: noop, statsOpen: true, setStatsOpen: noop, stats: null,
    codeIntelligence: null, traceEventCount: 2, onOpenTrace: noop, onOpenTranscript: noop,
  });
  const view = await render(WorkspaceHeaderActions, props("phone"));
  const root = view.root;
  assert.equal(root.findByProps({ className: "workspace__actions workspace__actions--compact" }).type, "div");
  assert.equal(text(root.findByProps({ className: "workspace__error-action" })), "Retry");
  assert.equal(root.findByProps({ "aria-label": "Open execution trace (2 events)" }).props["data-tooltip"], "Execution trace");
  act(() => root.findByProps({ "aria-label": "More chat actions" }).props.onClick());
  const items = root.findAllByProps({ role: "menuitem" }).map((item) => text(item));
  assert.equal(json(items), json(["Hide working files", "Export evidence PDF", "Export analysis JSON", "Open session transcript",
    "Open chat statistics", "Switch to dark theme"]));
  act(() => view.update(createElement(WorkspaceHeaderActions, props("desktop"))));
  assert.equal(root.findAllByProps({ "data-testid": "header-transcript" }).length, 1);
  assert.equal(json(root.findAllByProps({ role: "menuitem" }).map((item) => text(item))), json(["Export evidence PDF", "Export analysis JSON"]),
    "the open menu keeps its state when the width changes");
  act(() => view.unmount());
});

test("the workspace primary content gets its 88 props, with the agent selection passed as setSelectedAgentId", async () => {
  let seen;
  const { renderWorkspacePrimaryContent } = load("chat/workspacePrimaryContentRender.tsx", {
    WorkspacePrimaryContent: { WorkspacePrimaryContent: (p) => { seen = p; return createElement("div", { "data-testid": "primary" }); } },
  });
  const props = new Proxy({}, { get: (target, key) => (typeof key === "string" ? `v:${key}` : undefined) });
  const view = await render(() => renderWorkspacePrimaryContent(props), {});
  assert.equal(view.root.findAllByProps({ "data-testid": "primary" }).length, 1);
  const keys = Object.keys(seen);
  assert.equal(keys.length, 88);
  assert.equal(seen.setSelectedAgentId, "v:handleAgentSelection");
  assert.equal(seen.handleAgentSelection, undefined);
  assert.ok(keys.every((key) => key === "setSelectedAgentId" || seen[key] === `v:${key}`));
  assert.equal(json(keys.slice(0, 4)), json(["error", "selectedSession", "chatState", "selectedSessionIsRunning"]));
  assert.equal(keys.at(-1), "ttsEnabled");
  act(() => view.unmount());
});

test("inline tool executions show saved scripts, runs, Confluence results and diagrams", async () => {
  const { InlineToolExecutions } = load("chat/messageBubbleInlineTools.tsx", {
    DiagramViewer: { DiagramViewer: (p) => createElement("div", { "data-testid": "diagram", "data-id": p.diagramId ?? "", "data-url": p.fetchUrl ?? "" }) },
    messageBubbleToolArtifacts: { ToolArtifacts: (p) => createElement("div", { "data-testid": "artifacts", "data-count": p.artifacts.length }) },
    messageBubbleInlineConfluence: { ConfluenceDeltaInline: box("delta"), ConfluenceSyncInline: box("sync") },
  });
  const events = [
    { id: "1", toolName: "save_python_script", status: "completed", parameters: { name: "calc", purpose: "Sum", code: "print(1)" } },
    { id: "3", toolName: "run_saved_python_script", status: "completed", result: { name: "calc", exit_code: 0, stdout: "1", stderr: "" }, artifacts: [{ id: "a" }] },
    { id: "5", toolName: "list_confluence_page_updates", status: "completed", result: {} },
    { id: "6", toolName: "sync_confluence_knowledge_map", status: "completed", result: {} },
    { id: "7", toolName: "create_diagram", status: "completed", result: { diagram_xml: "<x/>", diagram_id: "d1" } },
    { id: "8", toolName: "edit_diagram", status: "completed", result: { _artifact_storage: "external_json_gzip", preview: { compact_result: { diagram_id: "d2" } } } },
    { id: "9", toolName: "create_diagram", status: "completed", result: {} },
    { id: "10", toolName: "web_search", status: "completed", result: {} },
  ];
  const view = await render(InlineToolExecutions, { events });
  const root = view.root;
  assert.equal(json(classes(root, "tool-inline__badge").map((node) => text(node))), json(["Python script saved", "Python execution"]));
  assert.equal(json(classes(root, "tool-inline__title").map((node) => text(node))), json(["calc", "calcexit 0"]));
  assert.equal(json(classes(root, "tool-inline__summary").map((node) => text(node))), json(["View generated code", "View execution output"]));
  assert.equal(root.findAllByProps({ "data-testid": "delta" }).length, 1);
  assert.equal(root.findAllByProps({ "data-testid": "sync" }).length, 1);
  const diagrams = root.findAllByProps({ "data-testid": "diagram" });
  assert.equal(json(diagrams.map((node) => [node.props["data-id"], node.props["data-url"]])),
    json([["d1", ""], ["d2", "/chat/api/artifact?path=diagram%3A%2F%2Fd2"]]));
  assert.equal(text(classes(root, "tool-inline__text--error")[0]), "No diagram XML returned.");
  assert.equal(root.findAllByProps({ "data-testid": "artifacts" }).length, 4);
  act(() => view.update(createElement(InlineToolExecutions, { events: [events.at(-1)] })));
  assert.equal(view.toJSON(), null);
  act(() => view.unmount());
});

test("a thread node shows its toggle, bulk checkbox, rename field, menu and folded sub-chats", async () => {
  const { createThreadNodeRenderer } = load("chat/ThreadGroupNode.tsx", {
    ThreadRowParts: { ThreadMarker: box("marker"), ThreadRenameInput: box("rename"), ThreadRowMeta: box("meta") },
    ThreadRowMenu: { ThreadRowMenu: (p) => createElement("div", { "data-testid": "menu", "data-select": String(Boolean(p.onSelect)) }) },
    threadSidebarIcons: { ThreadCheckboxBox: box("box"), ThreadChevronIcon: box("chevron"), ThreadMoreIcon: box("more") },
  });
  const toggled = [];
  const ctx = {
    expandedParents: { p2: true }, bulk: { isSelected: (id) => id === "p1", onToggleRow: noop }, bulkMode: false,
    renamingThreadId: "c1", setRenamingThreadId: noop, openMenuThreadId: "p1", setOpenMenuThreadId: noop,
    menuTriggers: { current: {} }, canDeleteThreads: true, toggleParent: (id) => toggled.push(id), runAction: async () => {},
    handleRowClick: noop, handleRowKeyDown: noop, startLongPress: noop, cancelLongPress: noop, onRename: noop,
    onPinToggle: noop, onArchive: noop, onExport: noop, onExportAnalysis: noop, onDelete: noop, onEnterBulk: noop, onRowHover: noop,
  };
  const t = (id, title, extra = {}) => ({ id, title, isSelected: false, startedAt: "2026-01-01T00:00:00Z", ...extra });
  const list = [t("p1", "One", { isSelected: true, subThreads: [t("c0", "Sub zero"), t("c9", "Sub nine")] }),
    t("p2", "Two", { subThreads: [t("c1", "Sub one")] })];
  const Host = () => createElement("div", null, list.map((thread) => createThreadNodeRenderer(ctx)(thread)));
  const view = await render(Host, {});
  const root = view.root;
  assert.equal(root.findAllByProps({ role: "treeitem" }).length, 3);
  assert.equal(root.findAllByType("input").length, 2);
  assert.equal(root.findAllByProps({ "data-testid": "rename" }).length, 1);
  assert.equal(json(classes(root, "thread-card__title-text").map((node) => text(node))), json(["One", "Two"]));
  assert.equal(root.findByProps({ "data-testid": "menu" }).props["data-select"], "true");
  assert.equal(root.findByProps({ "aria-label": "Actions for One" }).props["aria-expanded"], true);
  const folded = root.findByProps({ "data-testid": "thread-subchats-folded" });
  assert.equal(text(folded), "2 subchats");
  act(() => folded.props.onClick());
  assert.equal(json(toggled), json(["p1"]));
  assert.equal(classes(root, "thread-subtree").length, 1);
  assert.equal(classes(root, "thread-card--active").length, 1);
  act(() => view.unmount());
});
