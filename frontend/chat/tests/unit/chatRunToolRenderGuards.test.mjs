// Render guards for the tool burst, the run details and the "Run on" control: key text and structure stay the same
// when the components are split into smaller parts. Children and network modules are stubbed by module name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createContext, createElement } from "react";
import { act, box, load, noop, render, text } from "./renderGuardHarness.mjs";

const byClass = (root, name) => root.findAll((node) => typeof node.type === "string"
  && typeof node.props?.className === "string" && node.props.className.split(" ").includes(name));
const byTestId = (root, id) => root.findAll((node) => typeof node.type === "string" && node.props?.["data-testid"] === id);

test("a tool burst shows its tools, status, stats and one row per attempt", async () => {
  const { ToolBurst } = load("chat/ToolBurst.tsx", {
    ToolBurstEvent: { ToolBurstEvent: (p) => createElement("div", { "data-testid": "burst-event" }, p.event.id) },
  });
  const group = { status: "mixed", events: [
    { id: "e1", toolName: "read_file", status: "success", durationMs: 1200, artifacts: [{ id: "a" }] },
    { id: "e2", toolName: "write_file", status: "error", durationMs: 800 },
    { id: "e3", toolName: "read_file", status: "running" },
  ] };
  const root = (await render(ToolBurst, { group, actionsDisabled: false })).root;
  assert.equal(text(byClass(root, "tool-burst__prompt-copy")[0]), "Read File");
  assert.equal(text(byClass(root, "tool-burst__context")[0]), "Read File · Write File");
  const status = byClass(root, "tool-burst__status")[0];
  assert.equal(status.props.className, "tool-burst__status tool-burst__status--mixed");
  assert.equal(status.props.title, "1 successful, 1 failed");
  assert.deepEqual(byClass(root, "tool-burst__count").map(text), ["3 attempts", "1 ok", "1 error", "1 active"]);
  assert.equal(text(byClass(root, "tool-burst__meta")[0]), "1 output");
  assert.deepEqual(byClass(root, "tool-burst__duration").map(text), ["2.0 s", "2.0 s"]);
  assert.deepEqual(byTestId(root, "burst-event").map(text), ["e1", "e2", "e3"]);

  const single = (await render(ToolBurst, { group: { status: "success", events: [{ id: "e9", toolName: "", status: "completed" }] }, actionsDisabled: false })).root;
  assert.equal(text(byClass(single, "tool-burst__prompt-copy")[0]), "Tool usage");
  assert.equal(byClass(single, "tool-burst__context").length, 0);
  assert.equal(byClass(single, "tool-burst__duration").length, 0);
  assert.deepEqual(byClass(single, "tool-burst__count").map(text), ["1 step", "1 ok"]);
});

const runStubs = () => ({
  RunPayload: { RunPayload: box("payload") }, SpecStudioLink: { SpecStudioLink: box("studio") }, DecisionCard: { DecisionCard: box("decision") },
  PublishProveStatus: { PublishProveStatus: box("prove") }, PipelineAudit: { PipelineAudit: box("pipeline") },
  RunActionControls: { RunActionControls: (p) => createElement("div", { "data-testid": "actions" },
    `${p.actions.map((action) => action.key).join(",")}|${p.primary?.key ?? "-"}`) },
  RunHistory: { RunHistory: box("history") }, RunTokens: { RunTokens: box("tokens") }, ParallelWorkBoard: { ParallelWorkBoard: box("board") },
  RemedyAction: { RemedyWorkspaceContext: createContext(null) }, useRunResource: { useRunResource: () => ({ events: [], decisions: [] }) },
  TranscriptButton: { TranscriptLink: box("transcript") },
});

test("the run details show the phases, facts, notices, failure, actions and the details list", async () => {
  const { RunDetails } = load("chat/workflowRun/RunDetails.tsx", runStubs());
  const run = {
    id: "run-1", title: "Fix login", status: "failed", workflow_key: "ship", workflow_version: 3, updated_at: "2026-01-01T00:00:00Z",
    work_item: { key: "PET-1", title: "Login" }, project_id: "p1", branch: "feat/login",
    nodes: [{ id: "n1", kind: "phase", title: "Plan" }, { id: "n2", kind: "phase", title: "Build" }, { id: "n3", kind: "phase", title: "Test" }],
    current_node: { id: "n2" }, loops: [{ title: "Implement ↔ test", used: 2, limit: 3 }],
    actions: [{ key: "retry", label: "Retry" }, { key: "stop", label: "Stop", tone: "danger" }],
    waiting: { question: "Which way?", approval_id: "ap1" }, pause: { detail: "Paused for review" }, last_error: "Boom",
    failure: { findings: "3 tests fail", follow_up_issue: "PET-2" },
  };
  const props = { id: "d1", objectName: "run", inputs: {}, setInput: noop, valueOf: () => "", busy: false, onChoose: noop };
  const view = await render(RunDetails, { ...props, run });
  const root = view.root;
  const details = byTestId(root, "workflow-run-bar-details")[0];
  assert.equal(details.props.id, "d1");
  assert.equal(text(byClass(root, "run-bar__title")[0]), "PET-1 Login");
  assert.deepEqual(byClass(root, "workflow-run-steps__step").map((step) => [text(step), step.props.className.split("--")[1]]),
    [["Plan", "done"], ["Build", "problem"], ["Test", "pending"]]);
  assert.deepEqual(byClass(root, "run-bar__facts")[0].children.filter((c) => typeof c.type === "string").map((c) => text(c)),
    ["Implement ↔ test 2/3", "Branch feat/login", "Waiting approval ›"]);
  assert.equal(byTestId(root, "workflow-run-waiting-approval")[0].props.href, "/chat?area=operations&tab=approvalDetail&approval=ap1");
  assert.deepEqual(byClass(root, "run-bar__text").map(text), ["Paused for review", "Which way?", "Follow-up issue PET-2", "Boom"]);
  assert.equal(text(byClass(root, "workflow-run-banner__text")[0]), "3 tests fail");
  assert.equal(text(byTestId(root, "actions")[0]), "retry,stop|-");
  assert.deepEqual(byClass(root, "workflow-run-banner__details-list")[0].findAllByType("li").map(text), ["Workflow ship · version 3", "Run run-1"]);
  assert.deepEqual(view.toJSON().children.map((c) => c.props["data-testid"] ?? c.props.className),
    ["run-bar__title", "workflow-run-steps", "board", "run-bar__facts", "run-bar__text", "run-bar__text", "workflow-run-banner__payload",
      "pipeline", "prove", "studio", "payload", "run-bar__text", "actions", "history", "tokens", "workflow-run-details"]);

  const plain = (await render(RunDetails, { ...props, run: { id: "r2", title: "Plain", status: "running", workflow_key: "w", actions: [], nodes: [] } })).root;
  assert.equal(byTestId(plain, "workflow-run-steps").length, 0);
  assert.equal(byClass(plain, "run-bar__text").length, 0);
  assert.equal(text(byClass(plain, "run-bar__title")[0]), "Plain");
});

const devices = { items: [
  { id: "d1", name: "Mac", os: "macos", connected: true, running_jobs: 1, max_parallel_jobs: 2, profiles: ["governed", "seat"], seat_login: true, folders: ["/src", "/docs"] },
  { id: "d2", name: "Box", os: "linux", connected: false, last_seen_at: null, profiles: ["governed"], folders: [] },
] };

function loadRunOn(target, picked) {
  return load("chat/devices/RunOnControls.tsx", {
    DeviceModelPill: { DeviceModelPill: box("model-pill") },
    devicesApi: { loadMyDevices: async () => devices,
      loadDeviceRunsPolicy: async () => ({ project_id: "p1", enabled: true, allowed_profiles: ["governed", "seat"], seat_allowed: true }) },
    executionTarget: { SERVER_TARGET: { kind: "server" }, setExecutionTarget: (...args) => picked.push(args), useExecutionTarget: () => target },
  }).RunOnControls;
}

test("the Run on control lists the devices, picks one and shows folder, profile and model for a device", async () => {
  const picked = [];
  const RunOnControls = loadRunOn({ kind: "device", deviceId: "d1", folder: "/src", profile: "governed", model: "" }, picked);
  const view = await render(RunOnControls, { sessionId: "s1", projectId: "p1", workspaceName: "WS", composerDisabled: false });
  const root = view.root;
  assert.equal(byClass(root, "device-popover").length, 0);
  const pill = root.findAll((n) => n.type === "button" && n.props["aria-haspopup"] === "listbox")[0];
  assert.equal(text(pill), "Run on: Mac");
  assert.equal(pill.props.className, "composer-pill composer-pill--active");
  assert.deepEqual(root.findAllByType("option").map((o) => o.props.value), ["/src", "/docs", "governed", "seat"]);
  assert.equal(byTestId(root, "model-pill").length, 1);
  await act(async () => pill.props.onClick());
  const options = root.findAll((n) => n.type === "button" && n.props.role === "option");
  assert.deepEqual(options.map((o) => [text(o.findAllByType("b")[0]), o.props.disabled ?? false, o.props["aria-selected"]]),
    [["Server", false, false], ["Mac", false, true], ["Box", true, false]]);
  assert.equal(text(options[1].findAllByType("small")[0]), "macOS · online · 1 running (limit 2) · seat or governed");
  assert.equal(options[2].findAll((n) => typeof n.props?.className === "string" && n.props.className.startsWith("device-dot"))[0].props.className,
    "device-dot device-dot--off");
  assert.deepEqual(byClass(root, "device-pop-label").map(text), ["Platform", "My devices"]);
  await act(async () => options[1].props.onClick());
  assert.equal(JSON.stringify(picked[0]), JSON.stringify(["s1", { kind: "device", deviceId: "d1", folder: "/src", profile: "governed", model: "" }]));
  assert.equal(byClass(root, "device-popover").length, 0);
});

test("the Run on control on the server shows one pill and no device fields", async () => {
  const RunOnControls = loadRunOn({ kind: "server" }, []);
  const root = (await render(RunOnControls, { sessionId: "s1", projectId: "", workspaceName: "WS", composerDisabled: true })).root;
  const buttons = root.findAllByType("button");
  assert.equal(buttons.length, 1);
  assert.equal(text(buttons[0]), "Run on: Server");
  assert.equal(buttons[0].props.disabled, true);
  assert.equal(root.findAllByType("select").length, 0);
});
