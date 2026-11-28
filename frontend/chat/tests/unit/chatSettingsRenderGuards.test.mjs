// Render guards for chat components (composer popups, statistics, answer feedback, my devices, my notifications):
// key text and structure stay the same when the components are split into smaller parts. Heavy children and network
// modules are stubbed by module name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, load, noop, render, text } from "./renderGuardHarness.mjs";

const classes = (root, name) => root.findAll((node) => typeof node.props?.className === "string"
  && node.props.className.split(" ").includes(name) && typeof node.type === "string");

test("the composer shows the slash commands, the agent mentions and the draft attachments", async () => {
  const { ComposerInputEnhancements } = load("chat/ComposerInputEnhancements.tsx", {
    ChatShellIcons: { AttachIcon: () => createElement("i", null, "clip") },
  });
  const sent = [];
  const picked = [];
  const removed = [];
  const props = {
    fileInputRef: { current: null }, uploadDraftFiles: async () => {}, slashCommand: { open: true, query: "st" },
    slashCommands: [{ name: "status", description: "Show status" }, { name: "stop", description: "Stop run" }, { name: "help", description: "Help" }],
    setComposerValue: noop, setSlashCommand: noop, handleSend: async (prompt) => { sent.push(prompt); },
    atMention: { open: true, query: "" },
    groupedAgentOptions: [{ label: "Team", agents: [{ id: "a1", name: "Reviewer", description: "Reviews code" }, { id: "a2", name: "Tester" }] }],
    handleSelectAtAgent: (agent) => picked.push(agent.id),
    draftAttachments: [{ id: "f1", name: "notes.txt", url: "/f1", sizeBytes: 2048 }], uploadingAttachments: true,
    removeDraftAttachment: (id) => removed.push(id),
  };
  const view = await render(ComposerInputEnhancements, props);
  const root = view.root;
  assert.equal(root.findAllByType("input").length, 1);
  const command = classes(root, "composer-popup--command")[0];
  assert.deepEqual(classes(command, "composer-popup__name").map(text), ["/status", "/stop"]);
  act(() => classes(command, "composer-popup__item")[1].props.onMouseDown({ preventDefault: noop }));
  assert.deepEqual(sent, ["/stop"]);
  const mention = classes(root, "composer-popup--mention")[0];
  assert.equal(text(classes(mention, "composer-popup__group-label")[0]), "Team");
  assert.deepEqual(classes(mention, "composer-popup__name").map(text), ["@Reviewer", "@Tester"]);
  assert.equal(classes(mention, "composer-popup__desc").length, 1);
  act(() => classes(mention, "composer-popup__item")[0].props.onMouseDown({ preventDefault: noop }));
  assert.deepEqual(picked, ["a1"]);
  assert.equal(text(classes(root, "composer-attachments__count")[0]), "1");
  assert.match(text(classes(root, "composer-attachment-chip__label")[0]), /^notes\.txt/);
  assert.equal(text(classes(root, "composer-attachment-chip--status")[0]), "Uploading attachments…");
  act(() => root.findByProps({ title: "Remove notes.txt" }).props.onClick());
  assert.deepEqual(removed, ["f1"]);
  act(() => view.update(createElement(ComposerInputEnhancements, { ...props, slashCommand: { open: true, query: "zz" },
    atMention: { open: false, query: "" }, draftAttachments: [], uploadingAttachments: false })));
  assert.match(text(classes(root, "composer-popup__empty")[0]), /No command matches/);
  assert.equal(classes(root, "composer-popup--mention").length, 0);
  assert.equal(classes(root, "composer-attachments").length, 0);
  act(() => view.unmount());
});

const pageHeader = (props) => createElement("header", { "data-testid": "page-header" }, props.title, props.secondary ?? null);

test("my devices list the devices with their status, pause all and open a device's drawer", async () => {
  const raw = { all_paused: false, items: [
    { id: "dev_a", name: "Laptop", os: "macos", paused: false, connected: true, running_jobs: 2, max_parallel_jobs: 4,
      profiles: ["governed"], folders: ["/src", "/docs"], last_seen_at: null, client_version: "1.2.0", service_kind: "launchd" },
    { id: "dev_b", name: "Desktop", os: "linux", paused: false, connected: false, running_jobs: 0, max_parallel_jobs: 4,
      profiles: [], folders: [], last_seen_at: null },
  ] };
  const paused = [];
  const { MyDevicesPage } = load("chat/devices/MyDevicesPage.tsx", {
    devicesApi: { loadMyDevices: async () => raw, pauseAllDevices: async (value) => { paused.push(value);
      return { ...raw, all_paused: true, items: raw.items.map((item) => ({ ...item, paused: true })) }; } },
    PageHeader: { PageHeader: pageHeader },
    MyPhonesSection: { MyPhonesSection: () => createElement("div", { "data-testid": "phones" }) },
    DeviceDrawer: { DeviceDrawer: (p) => createElement("aside", { "data-testid": "drawer" }, p.device.name,
      createElement("button", { onClick: () => p.onRevoked(p.device.id) }, "Revoke")) },
  }, { setInterval: () => 1, clearInterval: noop, navigator: { clipboard: { writeText: async () => {} } } });
  const view = await render(MyDevicesPage, { pollMs: 1000 });
  const root = view.root;
  assert.equal(text(root.findByProps({ "data-testid": "page-header" })), "DevicesPause all my devices");
  const rows = root.findByType("tbody").findAllByType("tr");
  assert.deepEqual(rows.map((row) => row.findAllByType("td").map(text).slice(0, 5)), [
    ["LaptopmacOS · dev_a", "2 jobs", text(rows[0].findAllByType("td")[2]), "governed", "2"],
    ["DesktopLinux · dev_b", "Offline", text(rows[1].findAllByType("td")[2]), "—", "0"],
  ]);
  assert.equal(rows[1].props.className, "admin-panel__row--inactive");
  assert.equal(root.findAllByProps({ "data-testid": "phones" }).length, 1);
  await act(async () => { root.findByProps({ role: "switch" }).props.onClick(); });
  assert.deepEqual(paused, [true]);
  assert.match(text(root.findByProps({ className: "device-warn" })), /All your devices are paused/);
  assert.equal(root.findByProps({ role: "switch" }).props["aria-checked"], true);
  await act(async () => { root.findAllByProps({ className: "admin-panel__action-btn" }).find((node) => text(node) === "Copy").props.onClick(); });
  assert.ok(root.findAllByType("button").some((node) => text(node) === "Copied"));
  await act(async () => { rows[0].findByType("button").props.onClick(); });
  assert.equal(text(root.findByProps({ "data-testid": "drawer" })), "LaptopRevoke");
  await act(async () => { root.findByProps({ "data-testid": "drawer" }).findByType("button").props.onClick(); });
  assert.equal(root.findAllByProps({ "data-testid": "drawer" }).length, 0);
  assert.equal(root.findByType("tbody").findAllByType("tr").length, 1);
  act(() => view.unmount());
});

// A light table: every cell of every column, and the row menu.
const dataTable = (props) => createElement("table", { "data-testid": props.testId, "data-loading": String(Boolean(props.loading)) },
  createElement("tbody", null, props.rows.map((row) => createElement("tr", { key: props.rowKey(row) },
    ...props.columns.map((column) => createElement("td", { key: column.key }, column.render(row))),
    createElement("td", { key: "menu" }, props.rowMenu?.(row) ?? null)))));
const actionMenu = (props) => createElement("menu", null, props.items.map((item) =>
  createElement("button", { key: item.label, onClick: item.onSelect }, item.label)));
const dialog = (props) => createElement("dialog", { "data-testid": "confirm" }, props.title, props.error ?? null, props.children,
  createElement("button", { onClick: props.onConfirm }, props.confirmLabel));

test("my notifications list in-app and each channel with its switch, set up, test and remove", async () => {
  const sub = (channel, target, active) => ({ id: `s-${channel}`, user_id: "u1", project_id: null, event_type: "problem.raised",
    channel_type: channel, channel_config_id: null, target, template_id: null, is_active: active });
  let stored = [sub("email", "me@example.com", true), sub("slack", "C01", false)];
  const calls = [];
  const { MyNotificationsPage } = load("chat/notifications/MyNotificationsPage.tsx", {
    problemAlertsApi: { loadSubscriptions: async () => stored, saveSubscription: async (_scope, body, id) => { calls.push(["save", id, body.is_active]); },
      removeSubscription: async (_scope, id) => { calls.push(["remove", id]); stored = stored.filter((row) => row.id !== id); },
      sendTest: async (_scope, id) => { calls.push(["test", id]); } },
    PageHeader: { PageHeader: pageHeader }, DataTable: { DataTable: dataTable }, ActionMenu: { ActionMenu: actionMenu },
    ConfirmDialog: { ConfirmDialog: dialog }, StatusLabel: { StatusLabel: (p) => createElement("em", null, p.label) },
    ProblemAlertForm: { ProblemAlertForm: (p) => createElement("form", { "data-testid": "alert-form" }, p.title, " / ", p.primaryLabel) },
  });
  const view = await render(MyNotificationsPage, {});
  const root = view.root;
  const rows = root.findByProps({ "data-testid": "my-problem-alerts-table" }).findAllByType("tr");
  assert.deepEqual(rows.map((row) => row.findAllByType("td").slice(0, 3).map(text)), [
    ["In app", "Problems with your runs and device jobs, in the bell and on your phone", "Octryx"],
    ["Email", "Problems in your runs and in the Workspaces you administer", "me@example.com"],
    ["Slack", "Problems in your runs and in the Workspaces you administer", "C01"],
    ["Microsoft Teams", "Problems in your runs and in the Workspaces you administer", "Not set up"],
  ]);
  assert.equal(text(rows[0].findAllByType("td")[3]), "Always on");
  assert.deepEqual(root.findAllByProps({ role: "switch" }).map((node) => [node.props["aria-label"], node.props["aria-checked"]]),
    [["Email alerts", true], ["Slack alerts", false], ["Microsoft Teams alerts", false]]);
  assert.deepEqual(rows.map((row) => row.findAllByType("button").map(text)), [[], ["Change where it goes…", "Send test", "Remove…"],
    ["Change where it goes…", "Send test", "Remove…"], ["Set up…"]]);
  await act(async () => { root.findAllByProps({ role: "switch" })[1].props.onClick(); });
  assert.equal(JSON.stringify(calls.at(-1)), JSON.stringify(["save", "s-slack", true]));
  await act(async () => { root.findAllByProps({ role: "switch" })[2].props.onClick(); });
  assert.equal(text(root.findByProps({ "data-testid": "alert-form" })), "Microsoft Teams alerts / Turn on Microsoft Teams alerts");
  await act(async () => { rows[1].findAllByType("button")[1].props.onClick(); });
  assert.equal(text(root.findByProps({ "data-testid": "alerts-notice" })).length > 0, true);
  await act(async () => { rows[1].findAllByType("button")[2].props.onClick(); });
  assert.match(text(root.findByProps({ "data-testid": "confirm" })), /^Remove Email alerts\?Problems are no longer sent to me@example\.com\./);
  await act(async () => { root.findByProps({ "data-testid": "confirm" }).findAllByType("button").at(-1).props.onClick(); });
  assert.equal(root.findAllByProps({ "data-testid": "confirm" }).length, 0);
  assert.equal(JSON.stringify(calls.at(-1)), JSON.stringify(["remove", "s-email"]));
  act(() => view.unmount());
});

test("the chat statistics show the cards, the rows, the model costs and nothing without data", async () => {
  const { StatsPopover } = load("chat/StatsPopover.tsx", {
    statsPopoverSections: { codeIntelligenceSection: () => createElement("section", { "data-testid": "code" }),
      workflowRoiSection: () => createElement("section", { "data-testid": "roi" }),
      pullRequestsSection: (pullRequests) => createElement("section", { "data-testid": "prs" }, String(pullRequests.length)) },
  });
  const stats = { contextTokens: 1200, inputTokens: 3400, outputTokens: 560, requestCount: 7, llmRequestCount: 0, toolCallCount: 3,
    deterministicStepCount: 2, totalCost: 0.42, messageCount: 9, userMessageCount: 4, assistantMessageCount: 5, lastModel: "model-x",
    lastProvider: "provider-y", zeroCostReason: "Seat usage", cacheReadInputTokens: 10, cacheWriteInputTokens: 0, nonCachedInputTokens: 5,
    workflowRoi: { any: 1 },
    costByModel: [{ provider: "", model: "m1", cost: 0.4, requestCount: 3, inputTokens: 100, outputTokens: 50 }] };
  const view = await render(StatsPopover, { stats, codeIntelligence: { hasData: true } });
  const root = view.root;
  assert.deepEqual(classes(root, "stats-panel__card").map((node) => text(classes(node, "stats-panel__label")[0])),
    ["Context", "Input", "Output", "LLM requests", "Tool calls", "Workflow steps", "Cost"]);
  const values = classes(root, "stats-panel__value").map(text);
  assert.equal(values.length, 7);
  const rows = classes(root, "stats-panel__row").map((node) => node.findByType("span").children.join(""));
  assert.deepEqual(rows, ["Messages", "User", "Assistant", "Last model", "Provider", "Usage note", "Prompt cache",
    "Unknown provider / m1"]);
  assert.match(text(classes(root, "stats-panel__row")[6]), /non-cached · .* read · .* write$/);
  assert.match(text(classes(root, "stats-panel__row")[7]), / req · .* in · .* out$/);
  assert.equal(text(classes(root, "stats-panel__section-title")[0]), "Model cost");
  assert.equal(root.findAllByProps({ "data-testid": "roi" }).length, 1);
  assert.equal(root.findAllByProps({ "data-testid": "code" }).length, 1);
  assert.equal(text(root.findByProps({ "data-testid": "prs" })), "0");
  const pullRequests = [{ url: "https://git.example/pr/1", title: "PAY-1: Totals", state: "open", run_id: "r1" }];
  act(() => view.update(createElement(StatsPopover, { stats: null, codeIntelligence: null, pullRequests })));
  assert.equal(text(classes(root, "stats-panel__empty")[0]), "No usage data for this chat yet.");
  assert.equal(text(root.findByProps({ "data-testid": "prs" })), "1");
  act(() => view.update(createElement(StatsPopover, { stats: { ...stats, llmRequestCount: 1, lastModel: "", costByModel: [],
    cacheReadInputTokens: 0, nonCachedInputTokens: 0, workflowRoi: null }, codeIntelligence: null })));
  assert.deepEqual(classes(root, "stats-panel__row").map((node) => node.findByType("span").children.join("")),
    ["Messages", "User", "Assistant", "Provider", "Usage note"]);
  act(() => view.unmount());
});

test("the session's pull requests list title, link and state, and nothing without any", async () => {
  const { pullRequestsSection } = load("chat/statsPopoverSections.tsx", {});
  assert.equal(pullRequestsSection([]), null);
  const view = await render(() => pullRequestsSection([
    { url: "https://git.example/pr/1", title: "PAY-1: Totals", state: "open", run_id: "r1" },
    { url: "https://git.example/pr/2", title: "", state: "", run_id: null },
  ]), {});
  const links = view.root.findAllByType("a");
  assert.deepEqual(links.map((link) => [link.props.href, text(link)]),
    [["https://git.example/pr/1", "PAY-1: Totals"], ["https://git.example/pr/2", "https://git.example/pr/2"]]);
  assert.deepEqual(view.root.findAllByType("strong").map(text), ["open", "unknown"]);
  act(() => view.unmount());
});

test("the answer feedback opens its form, marks aspects, submits and shows the saved line", async () => {
  const { MessageFeedbackBar } = load("chat/messageBubbleFeedback.tsx", {
    messageBubbleIcons: { ThumbUpIcon: () => createElement("i", null, "up"), ThumbDownIcon: () => createElement("i", null, "down") },
  });
  const sent = [];
  const message = { id: "m1", role: "assistant", content: "hi", feedback: null };
  const props = { message, disabled: false, iconOnly: true, onSubmitFeedback: async (id, payload) => { sent.push([id, payload.rating]); } };
  const view = await render(MessageFeedbackBar, props);
  const root = view.root;
  const good = root.findByProps({ "aria-label": "This answer was good" });
  assert.equal(good.props.className, "message-feedback__button message-feedback__button--positive message-feedback__button--icon-only ");
  assert.equal(good.props["aria-expanded"], false);
  await act(async () => { root.findByProps({ "aria-label": "This answer was not good" }).props.onClick(); });
  const panel = root.findByProps({ id: "message-feedback-m1" });
  assert.equal(text(classes(panel, "message-feedback__panel-title")[0]), "The answer was not good");
  assert.equal(panel.findAllByType("textarea").length, 2);
  const chips = () => classes(root, "message-feedback__chip");
  assert.ok(chips().length >= 3);
  await act(async () => { chips()[0].props.onClick(); });
  assert.equal(chips()[0].props.className, "message-feedback__chip message-feedback__chip--liked");
  assert.equal(text(chips()[0]), "+ Correctness");
  await act(async () => { panel.findAllByType("textarea")[1].props.onChange({ target: { value: "too long" } }); });
  await act(async () => { classes(root, "message-feedback__submit")[0].props.onClick(); });
  assert.equal(JSON.stringify(sent), JSON.stringify([["m1", "bad"]]));
  assert.equal(root.findAllByProps({ id: "message-feedback-m1" }).length, 0);
  await act(async () => { view.update(createElement(MessageFeedbackBar, { ...props, message: { ...message, feedback: { rating: "bad", liked: "", disliked: "too long", aspects: {} } } })); });
  assert.equal(text(classes(root, "message-feedback__saved")[0]), "Thanks, your feedback is saved. You rated this answer bad.Edit");
  assert.equal(root.findByProps({ "aria-label": "This answer was not good" }).props["aria-pressed"], true);
  await act(async () => { classes(classes(root, "message-feedback__saved")[0], "message-feedback__cancel")[0].props.onClick(); });
  assert.equal(text(classes(root, "message-feedback__submit")[0]), "Update feedback");
  await act(async () => { classes(root, "message-feedback__cancel")[0].props.onClick(); });
  assert.equal(root.findAllByProps({ id: "message-feedback-m1" }).length, 0);
  act(() => view.update(createElement(MessageFeedbackBar, { ...props, message: { ...message, role: "user" } })));
  assert.equal(view.toJSON(), null);
  act(() => view.unmount());
});
