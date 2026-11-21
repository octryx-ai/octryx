// Render guards for phone pages (live session, chat, Work item, detail page switch): key text and structure stay the
// same when the pages are split into smaller parts. Data hooks, network modules and heavy children are stubbed by
// module name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, box, load, noop, render, text } from "./renderGuardHarness.mjs";

const json = (value) => JSON.stringify(value);
const classes = (root, name) => root.findAll((node) => typeof node.props?.className === "string"
  && node.props.className.split(" ").includes(name) && typeof node.type === "string");
const icon = (p) => createElement("i", { "data-icon": p.name });

test("a live session shows its steps, messages, pictures, the fork bar and the composer", async () => {
  const calls = [];
  const steps = Array.from({ length: 42 }, (_, i) => (i % 2 ? { kind: "tools", key: `g${i}` } : { kind: "step", key: `s${i}`, step: { id: i } }));
  const state = {
    messages: [{ id: "m1", direction: "out", text: "hi" }], running: true, draft: "go", setDraft: noop, busy: false, setBusy: noop,
    error: "Oops", setError: noop, pictures: [{ key: "p1", preview: "data:x" }], setPictures: noop, progress: steps, status: "working",
    forking: false, setForking: noop, allSteps: false, setAllSteps: noop, openKeys: new Set(), toggle: noop, picker: { current: null },
    end: { current: null }, seen: {}, refresh: noop,
  };
  const { LivePage } = load("mobile/LivePage.tsx", {
    useLiveSession: { useLiveSession: () => state },
    useFollowBottom: { useFollowBottom: () => [true, noop] },
    liveComposeActions: { liveComposeActions: () => ({ attach: async () => {}, submit: async () => calls.push("submit") }) },
    LiveSteps: { Step: box("step"), ToolGroup: box("tools") },
    liveMessageView: { renderLiveMessage: (m) => createElement("p", { key: m.id, "data-testid": "message" }, m.text) },
    mobileApi: { forkLive: async () => ({ thread_id: "t" }) },
    icons: { Icon: icon }, RunLine: { RunLineSubline: box("run-line") }, engineSeatModel: { runLine: () => "line" },
    mobileChatBrowser: { copy: noop },
    mobileLiveProgress: { progressSteps: (p) => p, groupSteps: (s) => s },
    liveTimeline: { buildLiveTimeline: (blocks, msgs) => [...blocks.map((block) => ({ type: "block", block })), ...msgs.map((message) => ({ type: "message", message }))] },
  });
  const view = await render(LivePage, { session: { name: "S", deviceName: "Mac" }, onBack: noop, onForked: noop });
  const root = view.root;
  assert.equal(text(root.findByType("strong")), "S");
  assert.equal(text(classes(root, "m-steps-more")[0]), "Show 2 earlier steps");
  assert.equal(root.findAllByProps({ "data-testid": "step" }).length + root.findAllByProps({ "data-testid": "tools" }).length, 40);
  assert.equal(root.findAllByProps({ "data-testid": "message" }).length, 1);
  assert.equal(text(root.findByProps({ role: "alert" })), "Oops");
  assert.equal(classes(root, "m-picture-chip").length, 1);
  assert.equal(text(classes(root, "m-new-below")[0]), "↓ New steps");
  assert.equal(classes(root, "m-fork-bar").length, 1);
  act(() => root.findByProps({ "aria-label": "Send" }).props.onClick());
  assert.equal(json(calls), json(["submit"]));
  act(() => view.unmount());
});

test("a phone chat shows messages, the live turn, cards, the state line and the dock", async () => {
  const page = {
    messages: [{ id: "u1", role: "user", content: "Q" }, { id: "a1", role: "assistant", content: "A" }], rawMessages: [], draft: "x",
    jobs: [{ id: "j1", events: [], approvals: [{ status: "pending" }], profile: "seat", deviceId: "d1" }], setDraft: noop,
    serverOptions: {}, setServerOptions: noop, busy: false, setBusy: noop, error: "", setError: noop, writes: [{ id: "w1" }],
    plans: [{ id: "p1" }], plansDecidedHere: { current: new Set() }, proposal: null, showProposal: noop, bottom: { current: null },
    turnOptions: {}, setTurnOptions: noop, refresh: async () => {},
  };
  const { ChatPage } = load("mobile/ChatPage.tsx", {
    useChatPageState: { useChatPageState: () => page }, useChatPolling: { useChatPolling: noop },
    chatPageSubmit: { chatPageSubmit: () => async () => {} },
    deviceJobsModel: { jobState: () => ({ live: true, tone: "running", label: "Running" }) }, deviceTurnView: { turnView: () => ({ items: [], finished: false }), turnBlocks: () => [{ kind: "text", key: "b1", text: "Thinking" }] },
    mobileApi: { stopJob: async () => {} }, MarkdownRenderer: { MarkdownRenderer: (p) => createElement("div", null, p.content) },
    mobileFilesArtifacts: { codeChanges: () => [], claudeArtifacts: () => [], macFiles: () => [], serverArtifacts: () => [] }, mobileUsageModel: { compactions: () => ({}), contextUsage: () => null }, mobileTurnOptions: { routeSuggestion: () => null }, mobileDeviceChats: { serverAnswerPending: () => false },
    Artifacts: { Artifacts: box("artifacts") }, MacFiles: { MacFiles: box("files") }, ServerOptionsBar: { ServerOptionsBar: box("server") },
    TurnOptionsBar: { TurnOptionsBar: box("turn-options") }, WriteApprovalCard: { WriteApprovalCard: box("write") },
    WritePlanApprovalCard: { WritePlanApprovalCard: box("plan") }, WorkflowProposalCard: { WorkflowProposalCard: box("proposal") },
    ChatPageHeader: { ChatPageHeader: box("header") }, JobApprovals: { JobApprovals: (p) => createElement("div", { "data-testid": "approvals", "data-pending": p.pending.length }) },
    JobCodeChanges: { JobCodeChanges: box("changes") }, icons: { Icon: icon }, mobileChatBrowser: { copy: noop, theme: () => "dark" },
  });
  const view = await render(ChatPage, { sessionId: "s1", title: "T", projectId: "p", onBack: noop });
  const root = view.root;
  assert.equal(text(classes(root, "m-user")[0]), "Q");
  assert.equal(json(classes(root, "m-ai").map((node) => text(node))), json(["A", "Thinking"]));
  assert.equal(root.findAllByProps({ "data-testid": "plan" }).length, 1);
  assert.equal(root.findAllByProps({ "data-testid": "write" }).length, 1);
  assert.equal(root.findByProps({ "data-testid": "approvals" }).props["data-pending"], 1);
  assert.equal(text(classes(root, "m-state")[0]), "Running");
  assert.equal(root.findAllByProps({ "data-testid": "turn-options" }).length, 1);
  assert.equal(root.findAllByProps({ "aria-label": "Stop" }).length, 1);
  assert.equal(root.findByProps({ id: "m-reply" }).props.placeholder, "Reply…");
  act(() => view.unmount());
});

test("a Work item on the phone shows facts, its run, the change plan and comments", async () => {
  const opened = [];
  const { CasePage } = load("mobile/CasePage.tsx", {
    mobileApi: { loadRun: async (id) => ({ run: { id, title: "Run T", status: "running" } }), loadTask: async () => ({}), loadTaskPlans: async () => ({}) },
    mobileTasksModel: { planStatusLabel: (s) => `Plan ${s}`, sourceLabel: (s) => (s ? "Jira" : ""), stateLabel: () => "Ready", readTaskDetail: () => ({ labels: ["l1"], issueType: "bug", description: "Desc", commentsTotal: 1,
        comments: [{ key: "c1", author: "Ann", created: "", body: "Nice" }] }), readTaskPlan: () => ({ status: "approved", version: 2, acceptance: 0, understood: "", openQuestions: ["Q1"] }) },
    mobileRuns: { isFinished: () => false, runTone: () => "running" },
    pullToRefresh: { useRefreshEvent: noop }, StatusLabel: { StatusLabel: (p) => createElement("span", null, p.label) },
    icons: { Icon: icon }, PageHeader: { DetailHeader: box("header") }, RunStart: { RunStart: box("run-start") },
  }, { window: { setInterval: () => 1, clearInterval: noop, setTimeout, clearTimeout }, document: { hidden: false } });
  const item = { id: "i1", key: "PET-1", title: "Login", state: "ready", priority: "high", assignee: "Bo", reporter: "", source: "jira",
    url: "http://j", projectId: "p", run: { id: "r1" } };
  const view = await render(CasePage, { item, workspace: "WS", onBack: noop, onOpenRun: (...args) => opened.push(args) });
  const root = view.root;
  const facts = root.findByProps({ className: "m-facts" }).findAllByType("dt").map((node) => text(node));
  assert.equal(json(facts), json(["State", "Priority", "Type", "Assignee", "Workspace", "Source"]));
  assert.equal(classes(root, "m-tag").length, 1);
  assert.equal(text(classes(root, "m-link")[0]), "Open in Jira");
  act(() => classes(root, "m-run-card")[0].props.onClick());
  assert.equal(json(opened), json([["r1", "PET-1 · Login"]]));
  assert.equal(root.findAllByProps({ "data-testid": "run-start" }).length, 0);
  assert.match(text(root.findByProps({ "aria-labelledby": "m-case-plan" })), /Plan approved · Version 2Open questionsQ1/);
  assert.equal(classes(root, "m-comment").length, 1);
  act(() => view.unmount());
});

test("the detail page switch opens one page per kind and returns null without a detail", () => {
  const names = ["ApprovalPage", "CasePage", "ChatPage", "DevicesPage", "LivePage", "LocalSessionPage", "NewChatSheet", "OperationsPage",
    "PluginPage", "RolePage", "RunPage", "SeatPage", "TerminalPage", "WorkspaceSwitcher"];
  const pages = Object.fromEntries(names.map((name) => [name, { [name]: box(name) }]));
  const { detailPage } = load("mobile/mobileDetailPages.tsx", { ...pages, mobileWorkspace: { newChatWorkspace: () => "w1" } });
  const opened = [];
  const props = {
    back: noop, openPage: (page) => opened.push(page), replacePage: noop, load: async () => {}, projects: [{ id: "w1" }, { id: "w2" }],
    workspace: "w1", workspaceNames: { w1: "One" }, cases: [{ id: "c1", assignee: "Ann" }], liveSessions: [], chooseWorkspace: noop,
    roleWorkspace: "w2", roleWorkspaceName: "Two", phonePages: [{ key: "k1" }], session: { user: { id: "u", name: "U" } }, pluginWorkspace: "w1",
  };
  const kinds = [["chat", { id: "t", title: "T", projectId: "w1" }, "ChatPage"], ["new", {}, "NewChatSheet"],
    ["local", { session: { id: "l" } }, "LocalSessionPage"], ["case", { item: { id: "c1", projectId: "w1" } }, "CasePage"],
    ["approval", { approval: { id: "a" } }, "ApprovalPage"], ["run", { runId: "r", title: "R" }, "RunPage"],
    ["live", { session: {} }, "LivePage"], ["terminal", { session: {} }, "TerminalPage"], ["devices", {}, "DevicesPage"],
    ["operations", {}, "OperationsPage"], ["seat", {}, "SeatPage"], ["role", {}, "RolePage"], ["plugin", { key: "k1" }, "PluginPage"]];
  for (const [kind, extra, name] of kinds) {
    const element = detailPage({ ...props, detail: { kind, ...extra } });
    assert.equal(element.type, pages[name][name], kind);
  }
  assert.equal(detailPage({ ...props, detail: null }), null);
  assert.equal(detailPage({ ...props, detail: { kind: "plugin", key: "missing" } }), null);
  const seat = detailPage({ ...props, detail: { kind: "seat" } });
  assert.equal(seat.key, "w2");
  assert.equal(seat.props.switcher.props.workspace, "w2");
  detailPage({ ...props, detail: { kind: "run", runId: "r", title: "R" } }).props.links.onOpenWorkItem({ id: "c1", key: "K", title: "T" });
  assert.equal(opened[0].item.assignee, "Ann");
});
