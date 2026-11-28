// Render guards for the phone's start card and home page: key text and structure stay the same when the components
// are split into smaller parts. Heavy children and network modules are stubbed by module name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, load, noop, render, text } from "./renderGuardHarness.mjs";

const classes = (root, name) => root.findAll((node) => typeof node.props?.className === "string"
  && node.props.className.split(" ").includes(name) && typeof node.type === "string");

function phoneStartCard() {
  return load("mobile/WorkflowStartCardPhone.tsx", {
    useEffectiveEngine: { useEffectiveEngine: () => "claude" },
    RunModelSelect: { useRunModelChoices: () => ({ options: [{ value: "", label: "Automatic" }, { value: "m1", label: "Model one" }],
      disabled: false, line: "Runs with Model one", hint: "Pick a model" }) },
  }).PhoneStartCard;
}

const START_VIEW = {
  workflowKey: "feature", projectId: "p1", workflowTitle: "Feature delivery", summary: "Build the login page",
  item: { mode: "new", typeLabel: "Story", title: "Login page", description: "A page to sign in", longDescription: false, key: null, href: null, id: null },
  jiraProject: "MM", jiraLabel: "+ Jira MM: Story", notes: ["Runs in phases"],
  runOn: { options: [{ key: "server", label: "Server", help: null, offline: false }, { key: "laptop", label: "My laptop", help: "Offline", offline: true }], selected: "server" },
  steps: ["Spec", "Build", "Review"],
  repository: { name: "web", id: "r1", sourceText: "named in your request", options: [{ id: "r1", name: "web" }, { id: "r2", name: "api" }] },
  outcome: { kind: "none" },
};

test("the phone start card shows the item, steps, repository, runs on, model and Start", async () => {
  const PhoneStartCard = phoneStartCard();
  const answers = [];
  const props = { card: { kind: "start", proposalId: "x", workflowKey: "feature", reason: "Matches your request", decided: null, view: START_VIEW },
    projectId: "p1", busy: null, error: "", onAnswer: async (decision, extra) => { answers.push([decision, extra]); }, onOther: noop,
    children: createElement("span", { "data-testid": "child" }, "child") };
  const view = await render(PhoneStartCard, props);
  const root = view.root;
  const card = root.findByProps({ "data-testid": "m-workflow-start" });
  assert.equal(card.props.className, "m-approval m-proposal m-start");
  assert.equal(text(classes(root, "m-eyebrow")[0]), "Start a workflow");
  assert.equal(text(root.findByType("h2")), "Build the login page");
  assert.equal(text(classes(root, "m-start-meta")[0]), "New Story");
  assert.equal(text(classes(root, "m-start-jira")[0]), "+ Jira MM: Story");
  assert.deepEqual(root.findByProps({ "aria-label": "Steps" }).findAllByType("li").map(text), ["Spec", "Build", "Review"]);
  assert.match(text(root.findByProps({ "data-testid": "m-workflow-start-repository" })), /Repository: web · named in your request/);
  assert.equal(root.findAllByType("select").length, 2);
  assert.deepEqual(root.findByProps({ "data-testid": "m-workflow-start-model" }).findAllByType("option").map(text), ["Automatic", "Model one"]);
  assert.deepEqual(classes(root, "m-buttons")[0].findAllByType("button").map(text).slice(1), ["Other workflow…", "Don't start"]);
  await act(async () => { root.findAllByType("select")[0].props.onChange({ target: { value: "laptop" } }); });
  assert.match(text(root), /Offline/);
  await act(async () => { classes(root, "m-primary")[0].props.onClick(); });
  assert.equal(JSON.stringify(answers), JSON.stringify([["apply", { runOn: "laptop" }]]));
  assert.equal(text(root.findByProps({ "data-testid": "child" })), "child");
  await act(async () => { view.update(createElement(PhoneStartCard, { ...props, card: { ...props.card, decided: "apply",
    view: { ...START_VIEW, outcome: { kind: "started", href: "/runs/1", runId: null, itemId: "i", itemKey: "MM-1", itemHref: null, jiraKey: "MM-2", jiraProblem: null } } } })); });
  assert.equal(card.props.className, "m-approval m-proposal m-start m-start-done");
  assert.equal(text(classes(root, "m-eyebrow")[0]), "Workflow started");
  assert.equal(root.findByProps({ "data-testid": "m-workflow-start-jira-key" }).props.children, "MM-2");
  assert.equal(classes(root, "m-link-button")[0].props.href, "/runs/1");
  assert.equal(classes(root, "m-buttons").length, 0);
  assert.equal(root.findAllByType("select").length, 0);
  await act(async () => { view.update(createElement(PhoneStartCard, { ...props, error: "Choose one", card: { ...props.card,
    view: { ...START_VIEW, outcome: { kind: "error", reason: "no budget", itemId: null, itemKey: null, itemHref: null, jiraKey: null, jiraProblem: null } } } })); });
  assert.equal(card.props.className, "m-approval m-proposal m-start m-start-failed");
  assert.deepEqual(root.findAllByProps({ role: "alert" }).map(text), ["Choose one", "Feature delivery did not start: no budget"]);
  act(() => view.unmount());
});

test("the phone home shows what needs the person, the tiles, the tasks and the recent chats", async () => {
  const { HomePage } = load("mobile/HomePage.tsx", {
    RedactedText: { RedactedText: (p) => createElement("span", null, p.value) },
    ChatList: { ChatRows: (p) => createElement("ul", { "data-testid": "chat-rows", "data-limit": String(p.limit) }) },
    icons: { Icon: (p) => createElement("i", { "data-icon": p.name }) },
    PageHeader: { TabHeader: (p) => createElement("header", { "data-testid": "tab-header" }, p.title, p.subtitle ?? null, p.switcher, p.actions) },
    pullToRefresh: { requestRefresh: async () => {} },
    TaskRow: { TaskRow: (p) => createElement("li", { "data-testid": "task" }, p.item.id, "@", p.workspace) },
  });
  const opened = [];
  const props = {
    switcher: createElement("span", null, "WS"), workspaces: { w1: "Claims" }, loading: false, error: "Offline",
    needs: [{ key: "n1", title: "Run stuck", subtitle: "Build", workspace: { name: "Claims" } }],
    approvals: [{ id: "a1", title: "Merge PR", workspaceId: "w1", requestedByName: "Sam", createdAt: null }],
    tiles: [{ key: "t1", label: "Runs", value: 3, hint: "running", tone: "attention", onOpen: () => opened.push("tile") }],
    threads: [{ id: "c1" }], sessions: [], cases: [{ id: "k1", projectId: "w1" }, { id: "k2", projectId: "w2" }, { id: "k3", projectId: "w1" }, { id: "k4", projectId: "w1" }],
    usage: { seat: { percent: 85, window: "5 h" }, budget: null, warn: true },
    onOpenItem: (item) => opened.push(item.key), onOpenApproval: (approval) => opened.push(approval.id), onOpenCase: noop,
    onOpenThread: noop, onOpenSession: noop, onAllChats: () => opened.push("all"), onNewChat: () => opened.push("new"),
  };
  const view = await render(HomePage, props);
  const root = view.root;
  assert.equal(text(root.findByProps({ "data-testid": "tab-header" })), "HomeSeat 85 % (5 h)WSNew chat");
  assert.equal(root.findByProps({ className: "m-warn" }).type, "span");
  assert.equal(text(root.findByProps({ role: "alert" })), "Offline");
  assert.equal(text(root.findByProps({ id: "m-needs" })), "Needs you 2");
  const needs = classes(root, "m-need");
  assert.match(text(needs[0]), /^Merge PRApproval · Claims · .*Sam/);
  assert.equal(text(needs[1]), "Run stuckBuild · Claims");
  act(() => needs[0].props.onClick());
  act(() => needs[1].props.onClick());
  assert.equal(classes(root, "m-tile-value")[0].props.className, "m-tile-value m-tile-attention");
  act(() => classes(root, "m-tile")[0].props.onClick());
  assert.deepEqual(root.findAllByProps({ "data-testid": "task" }).map(text), ["k1@Claims", "k2@", "k3@Claims"]);
  assert.equal(text(root.findByProps({ id: "m-yours" })), "Assigned to you 4");
  act(() => classes(root, "m-text-button")[0].props.onClick());
  assert.equal(JSON.stringify(opened), JSON.stringify(["a1", "n1", "tile", "all"]));
  assert.equal(root.findByProps({ "data-testid": "chat-rows" }).props["data-limit"], "4");
  act(() => view.update(createElement(HomePage, { ...props, error: "", needs: [], approvals: [], tiles: [], cases: [], threads: [], usage: null })));
  assert.equal(root.findAllByType("section").length, 1);
  assert.equal(text(classes(root, "m-empty")[0]), "No chats here yet.Start a chat");
  act(() => view.update(createElement(HomePage, { ...props, loading: true, threads: [] , sessions: [] })));
  assert.equal(text(classes(root, "m-empty")[0]), "Loading…");
  assert.equal(classes(root, "m-icon-button")[0].props.className, "m-icon-button m-spin");
  act(() => view.unmount());
});

test("a session handed over or waiting in the pool is taken over from Needs you, a refusal in its own words", async () => {
  const { HomePage } = load("mobile/HomePage.tsx", {
    RedactedText: { RedactedText: (p) => createElement("span", null, p.value) },
    ChatList: { ChatRows: () => createElement("ul") },
    icons: { Icon: (p) => createElement("i", { "data-icon": p.name }) },
    PageHeader: { TabHeader: (p) => createElement("header", null, p.title) },
    pullToRefresh: { requestRefresh: async () => {} },
    TaskRow: { TaskRow: () => createElement("li") },
  });
  const taken = [];
  let refuse = true;
  const props = {
    switcher: null, workspaces: {}, loading: false, error: "", approvals: [], tiles: [], threads: [], sessions: [], cases: [],
    usage: null, onOpenItem: noop, onOpenApproval: noop, onOpenCase: noop, onOpenThread: noop, onOpenSession: noop,
    onAllChats: noop, onNewChat: noop,
    needs: [{ key: "pool:p-1", kind: "pool", title: "Checkout copy", subtitle: "In the session pool", workspace: null },
      { key: "n1", kind: "problem", title: "Run stuck", subtitle: "", workspace: null }],
    onTakeOver: async (item) => {
      taken.push(item.key);
      if (refuse) throw new Error("Someone else took this session first.");
    },
  };
  const view = await render(HomePage, props);
  const root = view.root;
  const buttons = root.findAllByProps({ "data-testid": "m-take-over" }).filter((node) => typeof node.type === "string");
  assert.equal(buttons.length, 1, "only the pool entry is taken over here");
  await act(async () => buttons[0].props.onClick());
  assert.equal(text(root.findByProps({ role: "alert" })), "Someone else took this session first.");
  refuse = false;
  await act(async () => buttons[0].props.onClick());
  assert.deepEqual(taken, ["pool:p-1", "pool:p-1"]);
  assert.equal(root.findAllByProps({ role: "alert" }).length, 0);
  act(() => view.unmount());
});
