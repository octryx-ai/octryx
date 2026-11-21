// Render guards for phone pages (Work items list, a decision, notifications) and the key order of two admin state
// hooks: key text, structure and returned keys stay the same when they are split into smaller parts.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, box, icon, load, noop, render, text } from "./renderGuardHarness.mjs";

const byClass = (root, name) => root.findAll((node) => typeof node.type === "string"
  && typeof node.props?.className === "string" && node.props.className.split(" ").includes(name));

test("the phone Work items page shows filters, state chips, rows, the empty text and Show more", async () => {
  const asked = [];
  const page = { items: [{ id: "c1", projectId: "p1" }, { id: "c2", projectId: "p2" }], more: 20 };
  const { TasksPage } = load("mobile/TasksPage.tsx", {
    mobileApi: { loadCaseRuns: async () => [], loadTasks: async (query) => { asked.push(query); return page; } },
    mobileTasksModel: { nextOffset: (p) => p.more, readCases: (p) => p.items, stateLabel: (s) => `<${s}>`, readTaskCounts: () => ({ total: 5, states: [{ state: "open", label: "Open", count: 3 }, { state: "review", label: "Review", count: 2 }] }) },
    icons: { Icon: icon }, PageHeader: { TabHeader: (p) => createElement("header", null, `${p.title}|${p.subtitle ?? ""}`) },
    pullToRefresh: { useRefreshEvent: noop },
    TaskRow: { TaskRow: (p) => createElement("li", { "data-testid": "row" }, `${p.item.id}@${p.workspace}`) },
  });
  const view = await render(TasksPage, { workspaces: { p1: "Alpha" }, workspace: "", switcher: null, onOpen: noop });
  const root = view.root;
  assert.equal(text(root.findByType("header")), "Work items|5 open");
  assert.deepEqual(root.findAll((n) => n.type === "button").map(text), ["All", "Assigned to me", "All 5", "Open 3", "Review 2", "Show more"]);
  assert.deepEqual(root.findAll((n) => n.props["data-testid"] === "row" && n.type === "li").map(text), ["c1@Alpha", "c2@"]);
  assert.equal(JSON.stringify(asked[0]), JSON.stringify({ mine: false, state: "", q: "", offset: 0, project: "" }));
  await act(async () => root.findAll((n) => n.type === "button")[3].props.onClick());
  assert.equal(text(root.findByType("header")), "Work items|3 open");
  page.items = [];
  page.more = null;
  await act(async () => root.findAll((n) => n.type === "button")[1].props.onClick());
  assert.equal(text(root.findByType("header")), "Work items|3 open · assigned to you");
  assert.equal(text(byClass(root, "m-empty")[0]), "Nothing open is assigned to you in <open>.");
  act(() => view.unmount());
});

test("a phone decision shows the verdict, findings, questions, the note and both choices in order", async () => {
  const { DecisionCard } = load("mobile/DecisionCard.tsx", {
    StatusLabel: { StatusLabel: (p) => createElement("b", { "data-tone": p.tone }, p.label) },
    RunActions: { RunActionForm: (p) => createElement("button", { "data-primary": p.primary }, `${p.label}:${p.value ?? "-"}`) },
    RunPayload: { RunPayload: box("payload") },
  });
  const run = { id: "r1", actions: [{ key: "confirm", label: "Ship" }, { key: "change", label: "Fix" }], task_list: [] };
  const card = { subject: "decisions", verdict: "changes", heading: "Fix two things", summary: "Close", note: "Long note",
    findings: [{ file: "a.ts", line: 3, severity: "high", fix: "Guard null" }], questions: ["Keep the cache?"] };
  const view = await render(DecisionCard, { run, card, onDone: noop });
  const root = view.root;
  assert.equal(text(root.findByType("header")), "Your decisionFix two thingsNot ready to shipClose");
  assert.deepEqual(byClass(root, "m-section").map(text), ["Findings", "Assumptions to confirm"]);
  assert.equal(text(byClass(root, "m-finding")[0]).startsWith("Higha.ts:3Guard null"), true);
  assert.deepEqual(byClass(root, "m-field").map((n) => text(n.findByType("span"))), [
    "Your answer (optional; empty: fixed as proposed)", "1. Keep the cache?", "Anything else for the agent"]);
  assert.equal(text(byClass(root, "m-note")[0]), "Long note");
  await act(async () => root.findByType("input").props.onChange({ target: { value: "yes" } }));
  const foot = root.findByType("footer");
  assert.equal(text(foot.findByType("span")), "1 of 1 answered");
  assert.deepEqual(foot.findAllByType("button").map((n) => [text(n), n.props["data-primary"]]).map((x) => x[1]), [true, false]);
  assert.match(text(foot.findAllByType("button")[0]), /Keep the cache\?/);
  act(() => view.unmount());
});

test("phone notifications: loading, the switches with Turn off, and Turn on before subscribing", async () => {
  let state = { configured: true, subscribed: true, public_key: "k", rules: { needs_you: true, problem: false, done: true } };
  const saved = [];
  const { PushSettings } = load("mobile/PushSettings.tsx", {
    mobileApi: { loadPush: async () => state, savePush: async (body) => { saved.push(body); return state; }, deletePush: async () => state },
    mobilePush: { applicationServerKey: (k) => k, pushSupport: () => "ok" },
  }, { navigator: {} });
  const view = await render(PushSettings, {});
  const root = view.root;
  assert.equal(text(root.findByType("h2")), "Notifications");
  assert.deepEqual(root.findAll((n) => n.type === "li").map(text), ["Needs youApprovals, questions, seat and budget limits",
    "ProblemsYour runs and device jobs that are stuck or failed", "DoneFinished work"]);
  assert.deepEqual(root.findAll((n) => n.type === "input").map((n) => n.props.checked), [true, false, true]);
  assert.equal(text(root.findByType("button")), "Turn off notifications");
  await act(async () => root.findAll((n) => n.type === "input")[1].props.onChange());
  assert.equal(JSON.stringify(saved), JSON.stringify([{ rules: { needs_you: true, problem: true, done: true } }]));
  state = { ...state, subscribed: false };
  const second = await render(PushSettings, {});
  assert.equal(text(second.root.findByType("button")), "Turn on notifications");
  state = { ...state, configured: false };
  const third = await render(PushSettings, {});
  assert.equal(text(third.root.findByType("p")), "Notifications are not set up on this platform yet.");
  for (const v of [view, second, third]) act(() => v.unmount());
});

async function hookKeys(file, name, stubs = {}) {
  const hook = load(file, stubs)[name];
  let keys;
  const view = await render(() => { keys = Object.keys(hook()); return null; }, {});
  act(() => view.unmount());
  return keys;
}

test("the admin provider and webhook state hooks return their keys in the same order", async () => {
  const provider = await hookKeys("admin/hooks/useAdminProviderState.ts", "useAdminProviderState");
  assert.equal(provider.length, 74);
  assert.deepEqual(provider.slice(0, 6), ["copilotFlow", "setCopilotFlow", "editingKey", "setEditingKey", "expandedProvider", "setExpandedProvider"]);
  assert.equal(provider.join(","), PROVIDER_KEYS);
  const webhook = await hookKeys("admin/hooks/useAdminWebhookState.ts", "useAdminWebhookState");
  assert.equal(webhook.join(","), WEBHOOK_KEYS);
});

const pairs = (names) => names.flatMap((name) => [name, `set${name[0].toUpperCase()}${name.slice(1)}`]);
const PROVIDER_KEYS = pairs(["copilotFlow", "editingKey", "expandedProvider", "googleConnectLoading",
  "modelBudgetDrafts", "modelFilter", "modelOutputDrafts", "modelPricingInputDrafts", "modelPricingOutputDrafts", "modelSort",
  "modelsLoading", "newGoogleClientId", "newGoogleCloudProject", "newGoogleClientSecret", "newKeyValue", "newModelDisplay", "newModelId",
  "newModelMaxTokens", "newModelPlannerBudget", "newModelTools", "newProviderArn", "newProviderAuthMode", "newProviderDisplay",
  "newProviderEndpointUrl", "newProviderKey", "newProviderSecretKey", "newProviderSessionToken", "newProviderDriver", "newProviderRegion",
  "providerDrafts", "providerFormError", "providerFormLoading", "providerModels", "savingProviderConfig", "showAddModel",
  "showAddProvider", "syncingProvider"]).join(",");
const WEBHOOK_KEYS = [...pairs(["createdOutboundSigningSecret", "connectorWatcherEvents", "connectorWatcherRuleDecisions",
  "connectorWatcherRules", "connectorWatchers", "editingWebhookId"]), "filteredOutboundWebhookDeliveries",
...pairs(["outboundWebhookDeliveries", "outboundWebhookDeliverySearch", "outboundWebhookFormError", "outboundWebhookFormEvents",
  "outboundWebhookFormLoading", "outboundWebhookFormName", "outboundWebhookFormProjectId", "outboundWebhookFormUrl", "outboundWebhooks",
  "showCreateOutboundWebhook", "editingOutboundWebhookId", "showCreateWebhook", "showOutboundDeliveries", "webhookFormActive",
  "webhookFormAgentType", "webhookFormDescription", "webhookFormError", "webhookFormLoading", "webhookFormName", "webhookFormProjectId",
  "webhookFormSourceType", "webhooks"])].join(",");

test("the Copilot device flow polls, follows a slower interval, then marks the provider connected", async () => {
  const timers = [];
  const cleared = [];
  const answers = [{ flow_id: "f", user_code: "U", verification_uri: "https://v", interval: 5 },
    { status: "waiting", interval: 9 }, { status: "connected", login: "octo" }];
  const asked = [];
  const { createCopilotActions } = load("admin/hooks/useAdminProviderCopilotActions.ts", {}, {
    setInterval: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearInterval: (id) => cleared.push(id),
  });
  let flow = null;
  let providers = [{ id: "p1" }, { id: "p2" }];
  const ref = { current: null };
  const actions = createCopilotActions({
    readJson: async (url, init) => { asked.push([url.split("/").pop(), init.body ?? null]); return answers.shift(); },
    setCopilotFlow: (next) => { flow = typeof next === "function" ? next(flow) : next; },
    setProviders: (next) => { providers = next(providers); }, copilotPollRef: ref,
  });
  await actions.handleCopilotConnect("p1");
  assert.equal(JSON.stringify(flow), JSON.stringify({ providerId: "p1", flowId: "f", userCode: "U", verificationUri: "https://v", interval: 5, status: "pending" }));
  assert.deepEqual([timers[0].ms, ref.current], [5000, 1]);
  await timers[0].fn();
  assert.deepEqual([timers[1].ms, ref.current, cleared], [9000, 2, [1]]);
  assert.equal(flow.status, "waiting");
  assert.equal(flow.interval, 9);
  await timers[1].fn();
  assert.deepEqual([ref.current, cleared], [null, [1, 2]]);
  assert.equal(JSON.stringify([flow.status, flow.login, providers]), JSON.stringify(["connected", "octo",
    [{ id: "p1", has_api_key: true, api_key_masked: "OAuth: octo" }, { id: "p2" }]]));
  assert.equal(JSON.stringify(asked), JSON.stringify([["start", null], ["poll", "{\"flow_id\":\"f\"}"], ["poll", "{\"flow_id\":\"f\"}"]]));
  actions.handleCopilotDisconnect();
  assert.equal(flow, null);
});
