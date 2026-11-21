// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminChannelsTable.test.mjs
//
// Channels › Overview has no count cards and no "Channels (n)" header; the channels
// are one compact table (Name, Type, Workspace, State, Updated) whose row opens a side panel with the details and
// the actions: Configure as the primary rightmost, Enable/Disable and Reload beside it, Remove in the ⋯ menu.
// Outbound messages and channel sessions are compact tables too, with statuses in words.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { makeLoader, text } from "./automationTestLoader.mjs";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const CHANNELS = [
  { id: 1, plugin_id: "msteams", name: "Teams Ops", description: "Ops bot", project_id: "p1", project_name: "Ops",
    enabled: true, config: {}, status: "running", updated_at: null, config_fields: [] },
  { id: 2, plugin_id: "slack", name: "Slack Dev", description: "", project_id: null, project_name: null,
    enabled: false, config: {}, status: "stopped", updated_at: null, config_fields: [] },
];

const loader = makeLoader({ "/AdminHeaderSlot": { AdminHeaderActions: ({ children }) => children } });

function mountTab(overrides = {}) {
  const { AdminChannelsTab } = loader("admin/components/AdminChannelsTab.tsx");
  const calls = [];
  const noop = () => {};
  const ctx = new Proxy({
    channels: CHANNELS, channelSessions: [], channelDeliveryTargets: [], channelDeliveryLogs: [], projects: [],
    availableChannels: [], filteredAvailableChannels: [], configuringChannel: null, showAddChannel: false,
    channelFormValues: {}, channelConfigJson: "{}", channelFormName: "", channelFormProjectId: "",
    channelDeliveryProjectId: "", channelDeliveryEventType: "approval.requested", channelDeliveryChannelId: "",
    channelDeliveryTarget: "", channelCatalogSearch: "",
    getChannelIconColor: () => "inherit", renderChannelIcon: () => null, formatRelativeTime: () => "just now",
    readJson: async (url, init) => { calls.push([init?.method ?? "GET", url]); return {}; },
    reloadChannelsTab: () => calls.push(["reload"]),
    setConfiguringChannel: (value) => calls.push(["configure", value?.name]),
    ...overrides,
  }, { get: (target, key) => (key in target ? target[key] : noop) });
  let view;
  act(() => { view = TestRenderer.create(createElement(AdminChannelsTab, { ctx })); });
  return { view, calls };
}

const byTestId = (view, id) => view.root.findAll((node) => typeof node.type === "string" && node.props["data-testid"] === id);

test("Overview: no count cards and no Channels (n) header; one table row per channel with its state in words", () => {
  const { view } = mountTab();
  const all = text(view.root);
  assert.equal(view.root.findAll((node) => /admin-overview-card/.test(String(node.props?.className || ""))).length, 0);
  assert.doesNotMatch(all, /Channels \(2\)/);
  assert.equal(byTestId(view, "channels-table").length, 1);
  const rows = view.root.findAll((node) => node.type === "tr" && node.props["data-row-key"]);
  assert.deepEqual(rows.map((row) => row.props["data-row-key"]), ["1", "2"]);
  const states = rows.map((row) => row.findAll((node) => String(node.props.className || "").startsWith("ds-status")).map(text)[0]);
  assert.deepEqual(states, ["Running", "Off"]);
});

test("a row opens the side panel; Configure is the primary rightmost action, Remove sits in the ⋯ menu", () => {
  const { view, calls } = mountTab();
  const row = view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === "1");
  act(() => row.props.onClick());
  const panel = byTestId(view, "channel-panel")[0];
  assert.ok(panel, "the channel's side panel is open");
  assert.match(text(panel), /Ops bot/);
  const footer = panel.find((node) => node.props.className === "ds-panel__footer");
  const buttons = footer.findAll((node) => node.type === "button").map((node) => [text(node).trim(), node.props.className]);
  const labels = buttons.map(([label]) => label);
  assert.equal(labels.at(-1), "Configure");
  assert.match(buttons.at(-1)[1], /admin-panel__action-btn--primary/);
  assert.ok(labels.includes("Disable") && labels.includes("Reload"));
  assert.ok(!labels.includes("Remove"), "Remove is not a footer button");
  const header = panel.find((node) => node.props.className === "ds-panel__header-actions");
  assert.equal(header.findAll((node) => node.type === "button" && node.props["aria-label"] === "More actions for Teams Ops").length, 1,
    "Remove is in the ⋯ menu of the panel header");

  act(() => footer.find((node) => node.type === "button" && text(node).trim() === "Configure").props.onClick());
  assert.deepEqual(calls.at(-1), ["configure", "Teams Ops"], "Configure opens the existing configuration");
  assert.equal(byTestId(view, "channel-panel").length, 0, "the side panel closes for it");
});

test("Outbound messages: no count cards; statuses read in words with their colour", () => {
  const { AdminChannelDeliveryLogPanel, deliveryStatus } = loader("admin/components/AdminChannelDeliveryLogPanel.tsx");
  assert.deepEqual({ ...deliveryStatus("dead_letter") }, { label: "Failed, no more retries", tone: "problem" });
  assert.deepEqual({ ...deliveryStatus("sent") }, { label: "Sent", tone: "neutral" });
  assert.deepEqual({ ...deliveryStatus("some_new_state") }, { label: "Some new state", tone: "neutral" });
  const log = { id: "l1", notification_id: null, subscription_id: null, template_id: null, user_id: null, project_id: null,
    event_type: "approval.requested", channel_type: "teams", channel_config_id: 1, target: "19:abc", status: "dead_letter",
    retry_count: 3, last_error: "403", created_at: null, sent_at: null };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminChannelDeliveryLogPanel, {
      logs: [log], channels: CHANNELS, projects: [], formatRelativeTime: () => "now", onSetUpChannel: () => {},
    }));
  });
  assert.equal(view.root.findAll((node) => /admin-overview-card/.test(String(node.props?.className || ""))).length, 0);
  assert.match(text(view.root), /Failed, no more retries/);
  assert.doesNotMatch(text(view.root), /dead_letter/);
});
