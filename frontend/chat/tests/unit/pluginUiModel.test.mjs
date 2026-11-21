// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/pluginUiModel.test.mjs
// Plugin UI model: frame messages, the method allow-check, slots, the settings form, words.
import assert from "node:assert/strict";
import { test } from "node:test";

import { bridgeContext, bridgeRequestError, clampHeight, collectSlots, confirmationOf, frameLoadError, frameSrc, methodAllowed, pagesOfArea, parseSlotKey, readBridgeOutcome, readFrameMessage, slotsOf, themeTokens, toolWords } from "../../src/admin/components/plugins/pluginUiModel.ts";
import { settingsDraft, settingsErrorText, settingsFields, settingsPayload } from "../../src/admin/components/plugins/pluginSettingsModel.ts";

const refusal = (status, code, message) => Object.assign(new Error(message || code), { status, code });

test("only v:1 messages of a known shape count; heights are clamped to 120…4000 px", () => {
  assert.deepEqual(readFrameMessage({ v: 1, type: "ready" }), { kind: "ready" });
  assert.deepEqual(readFrameMessage({ v: 1, type: "resize", height: 50 }), { kind: "resize", height: 120 });
  assert.deepEqual(readFrameMessage({ v: 1, type: "resize", height: 99999 }), { kind: "resize", height: 4000 });
  assert.equal(readFrameMessage({ v: 1, type: "resize", height: "tall" }), null);
  assert.deepEqual(readFrameMessage({ v: 1, id: "c1", method: "list_jira_versions", params: { a: 1 } }),
    { kind: "call", id: "c1", method: "list_jira_versions", params: { a: 1 } });
  assert.deepEqual(readFrameMessage({ v: 1, id: "c2", method: "settings.get", params: [1] }).params, {}, "params are an object");
  for (const bad of [null, "ready", { type: "ready" }, { v: 2, type: "ready" }, { v: 1, type: "context" }, { v: 1, id: "", method: "x" },
    { v: 1, id: "c1" }, { v: 1, id: 7, method: "x" }, { v: 1, id: "x".repeat(65), method: "x" }]) {
    assert.equal(readFrameMessage(bad), null, JSON.stringify(bad));
  }
  assert.equal(clampHeight(Number.NaN), null);
});

test("only declared methods reach the bridge; a platform install names the viewer's Workspace", () => {
  const view = { methods: ["list_jira_versions", "settings.get"] };
  assert.equal(methodAllowed(view, "settings.get"), true);
  assert.equal(methodAllowed(view, "create_confluence_page"), false);
  assert.equal(methodAllowed(null, "settings.get"), false, "no view yet: nothing is sent");
  assert.deepEqual(bridgeContext("platform", "ws-1"), { workspace_id: "ws-1" });
  assert.deepEqual(bridgeContext("workspace", "ws-1"), {}, "a Workspace install runs in its own Workspace");
});

test("the frame address joins base URL and entry and never leaves the bundle", () => {
  const view = { base_url: "/plugin-ui/i1/tok/" };
  assert.equal(frameSrc(view, { entry: "index.html" }), "/plugin-ui/i1/tok/index.html");
  assert.equal(frameSrc(view, { entry: "pages/phone.html" }), "/plugin-ui/i1/tok/pages/phone.html");
  assert.equal(frameSrc(view, { entry: "../../other/index.html" }), "/plugin-ui/i1/tok/index.html");
  assert.equal(frameSrc({ base_url: "/plugin-ui/i1/tok" }, null), "/plugin-ui/i1/tok/index.html");
});

test("bridge answers: result, error, confirmation; refused requests keep their code", () => {
  assert.deepEqual(readBridgeOutcome({ result: { versions: [] } }), { result: { versions: [] } });
  const confirm = readBridgeOutcome({ error: { code: "confirmation_required", message: "Confirm this action in Octryx.",
    approval: { approval_id: "a1", change_preview_id: "p1", tool_name: "create_confluence_page" } } });
  assert.deepEqual(confirmationOf(confirm), { approval_id: "a1", change_preview_id: "p1", tool_name: "create_confluence_page" });
  assert.equal(confirmationOf(readBridgeOutcome({ error: { code: "tool_refused", message: "No Jira connection." } })), null);
  assert.equal(confirmationOf({ result: 1 }), null);
  assert.equal(readBridgeOutcome("nonsense").error.code, "bridge_failed");
  assert.deepEqual(bridgeRequestError(refusal(403, "plugin_method_not_declared", "'x' is not a method this plugin declares.")),
    { code: "plugin_method_not_declared", message: "'x' is not a method this plugin declares." });
  assert.deepEqual(bridgeRequestError(refusal(409, "plugin_disabled", "plugin_disabled")), { code: "plugin_disabled", message: "The plugin is disabled." });
});

test("a frame that cannot load says so in one line, with the server's message as its title", () => {
  assert.deepEqual(frameLoadError(refusal(404, "plugin_disabled", "The plugin is disabled.")), { text: "Plugin could not load", title: "The plugin is disabled." });
  assert.deepEqual(frameLoadError(refusal(404, "plugin_has_no_ui", "plugin_has_no_ui")), { text: "Plugin could not load", title: "This plugin brings no pages." });
  assert.equal(frameLoadError(refusal(403, "", "Forbidden")).title, "Forbidden");
});

test("tool names read in words", () => {
  assert.equal(toolWords("create_confluence_page"), "Create Confluence page");
  assert.equal(toolWords("mcp__release_bot__publish_notes"), "Publish notes");
  assert.equal(toolWords("release-bot.post_to_github"), "Post to GitHub");
  assert.equal(toolWords(""), "Change something");
});

const install = (over = {}) => ({ id: "i1", plugin: "octryx.release-notes", name: "Release notes", scope: "workspace", status: "active",
  ui: { bundle: "ui/dist", methods: [], pages: [{ id: "releases", title: "Releases", where: "work", entry: "index.html" }],
    tiles: [{ id: "ready", title: "Release readiness", where: "workspace" }], tabs: [], phone: [{ id: "releases", title: "Releases" }] }, ...over });

test("slots come from active installs with a bundle; pages group per plugin and area", () => {
  const entries = collectSlots([
    install(),
    install({ id: "i2", name: "Incident review", status: "disabled" }),
    install({ id: "i3", name: "Audit pack", ui: { bundle: null, pages: [{ id: "x", title: "X", where: "work" }] } }),
    install({ id: "i4", name: "Architecture", scope: "platform", ui: { bundle: "ui", pages: [{ id: "adr", title: "Decisions", where: "knowledge" }, { id: "map", title: "Map", where: "work" }] } }),
  ]);
  assert.deepEqual(entries.map((entry) => entry.key), ["i1:releases", "i1:ready", "i1:releases", "i4:adr", "i4:map"]);
  const work = pagesOfArea(entries, "work");
  assert.deepEqual(work.map((group) => [group.pluginName, group.pages.map((page) => page.slot.title)]), [["Architecture", ["Map"]], ["Release notes", ["Releases"]]]);
  assert.deepEqual(pagesOfArea(entries, "knowledge")[0].pages[0].scope, "platform");
  assert.deepEqual(slotsOf(entries, "phone").map((entry) => entry.slot.title), ["Releases"]);
  assert.deepEqual(slotsOf(entries, "tiles", "operations"), []);
  assert.deepEqual(parseSlotKey("0b6c-11:releases"), { installId: "0b6c-11", slotId: "releases" });
  assert.equal(parseSlotKey("i1:../x"), null);
});

const SCHEMA = {
  type: "object",
  required: ["confluence_space", "api_token"],
  properties: {
    audience: { type: "string", enum: ["customers", "team"], default: "customers", title: "Default audience" },
    confluence_space: { type: "string", title: "Confluence space", description: "Where release pages go." },
    max_tickets: { type: "integer" },
    ratio: { type: "number" },
    draft_first: { type: "boolean", default: true },
    api_token: { type: "string", format: "password", title: "API token" },
    webhook_secret: { type: "string", "x-secret": true },
  },
};

test("settings fields from the schema: types, labels, defaults; a secret only says whether it is set", () => {
  const fields = settingsFields(SCHEMA, { confluence_space: "REL", api_token: { set: true }, webhook_secret: { set: false } });
  assert.deepEqual(fields.map((field) => [field.key, field.control, field.label, field.required]), [
    ["audience", "enum", "Default audience", false],
    ["confluence_space", "text", "Confluence space", true],
    ["max_tickets", "integer", "Max tickets", false],
    ["ratio", "number", "Ratio", false],
    ["draft_first", "boolean", "Draft first", false],
    ["api_token", "secret", "API token", true],
    ["webhook_secret", "secret", "Webhook secret", false],
  ]);
  assert.equal(fields[0].value, "customers", "the default when nothing is stored");
  assert.equal(fields[1].value, "REL");
  assert.equal(fields[5].secretSet, true);
  assert.equal(fields[5].value, null, "never a secret's value");
  assert.equal(fields[6].secretSet, false);
});

test("the PUT body: numbers parsed, empty plain cleared, empty secret kept, required checked", () => {
  const fields = settingsFields(SCHEMA, { confluence_space: "REL", api_token: { set: true } });
  const draft = { ...settingsDraft(fields), max_tickets: "25", ratio: "0.5", draft_first: false };
  const { values, problems } = settingsPayload(fields, draft);
  assert.deepEqual(problems, {});
  assert.deepEqual(values, { audience: "customers", confluence_space: "REL", max_tickets: 25, ratio: 0.5, draft_first: false });
  assert.equal("api_token" in values, false, "an empty secret keeps the stored one");
  const typed = settingsPayload(fields, { ...draft, api_token: " new-value " }).values;
  assert.equal(typed.api_token, "new-value");
  const bad = settingsPayload(settingsFields(SCHEMA, {}), { ...settingsDraft(settingsFields(SCHEMA, {})), max_tickets: "2.5", ratio: "x" });
  assert.deepEqual(bad.problems, { confluence_space: "Required.", max_tickets: "A whole number.", ratio: "A number.", api_token: "Required." });
  assert.equal(settingsPayload(fields, { ...draft, max_tickets: "" }).values.max_tickets, null, "an emptied optional field is cleared");
});

test("refused settings read in words", () => {
  assert.equal(settingsErrorText(refusal(422, "plugin_setting_required", "'confluence_space' is required.")),
    "A required setting is missing: 'confluence_space' is required.");
  assert.equal(settingsErrorText(refusal(422, "plugin_setting_invalid", "plugin_setting_invalid")), "A value does not fit the setting.");
  assert.equal(settingsErrorText(refusal(422, "plugin_setting_unknown", "Unknown settings: x.")), "The plugin does not know a setting: Unknown settings: x.");
  assert.equal(settingsErrorText(refusal(403, "", "")), "Only who may install this plugin changes its settings.");
});

test("theme tokens: the first host variable with a value, and the background behind the frame", () => {
  const vars = { "--text": "#efece4", "--muted": " #898f86", "--border": "rgba(1,1,1,.1)", "--accent": "#e8dfc5", "--status-active": "#79b88e", "--status-error": "#f87171" };
  const tokens = themeTokens((name) => vars[name] ?? "", "rgb(14, 16, 15)");
  assert.equal(tokens.bg, "rgb(14, 16, 15)");
  assert.equal(tokens.fg, "#efece4");
  assert.equal(tokens.muted, "#898f86");
  assert.equal(tokens.line, "rgba(1,1,1,.1)", "falls back to --border");
  assert.equal(tokens.ok, "#79b88e");
  assert.equal(tokens.bad, "#f87171");
  assert.equal("panel" in tokens, false, "missing variables are left out");
});
