// Render guards for admin parts split into smaller functions: a prompt key's detail hook with its lifecycle actions,
// a group's data access attributes, the emergency stop panel and the held-starts notice, the Workspace transcript
// setting and a plugin's settings form behave and render the same.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, plain } from "./adminGuardRenderers.mjs";
import { loadStubbed, stubs } from "./adminGuardStubLoader.mjs";
import { button, hostCount } from "./adminGuardTreeReaders.mjs";

test("the prompt detail hook loads, runs each lifecycle action with its notice and reloads after a refused self-publish", async () => {
  const calls = [];
  const fail = new Set();
  const step = (name, answer = {}) => async (...args) => {
    calls.push([name, ...args]);
    if (fail.has(name)) throw Object.assign(new Error("refused"), { status: 409, code: "x" });
    return answer;
  };
  const api = { get: step("get", { key: "k" }), diff: step("diff", { lines: [] }), submit: step("submit"),
    publish: step("publish", { approval_gate: null }), approve: step("approve"), reject: step("reject"), retire: step("retire"), revert: step("revert") };
  const { usePromptDetail } = loadStubbed("admin/components/promptCatalog/usePromptCatalog.ts", [], {}, { "./promptCatalogApi": { promptCatalogApi: api } });
  let model;
  const changed = [];
  const Host = () => { model = usePromptDetail("k", () => changed.push(1), api); return null; };
  await createAsync(createElement(Host));
  assert.deepEqual(plain(model.detail), { key: "k" });
  assert.equal(model.busy, null);
  const expected = [
    ["submit", ["v1"], "Submitted: another person who may change this scope approves it from their Inbox."],
    ["publish", ["v1", "a1"], "Published: the next turn uses this version."],
    ["approve", ["a1"], "Approved: publish it now, or the author publishes it."],
    ["reject", ["a1"], "Rejected: the author can write a new draft."],
    ["retire", ["v1"], "Retired."],
    ["revert", ["k"], "Reverted: the next turn uses the shipped text again."],
  ];
  for (const [name, args, notice] of expected) {
    let ok;
    await act(async () => { ok = await model[name](...args); });
    assert.equal(ok, true, name);
    assert.equal(model.notice, notice, name);
  }
  assert.equal(changed.length, 6);
  await act(async () => { await model.showDiff("v2"); });
  assert.deepEqual(plain(model.diff), { lines: [] });
  act(() => model.clearDiff());
  assert.equal(model.diff, null);
  calls.length = 0;
  await act(async () => { assert.equal(await model.publishSelfApproved("v1", "draft"), true); });
  assert.deepEqual(calls.map(([name]) => name), ["submit", "publish", "get"]);
  assert.deepEqual(calls[1], ["publish", "v1", null, true]);
  fail.add("publish");
  calls.length = 0;
  await act(async () => { assert.equal(await model.publishSelfApproved("v1", "draft"), false); });
  assert.deepEqual(calls.map(([name]) => name), ["submit", "publish", "get"]);
  calls.length = 0;
  await act(async () => { assert.equal(await model.publishSelfApproved("v1", "in_review"), false); });
  assert.deepEqual(calls.map(([name]) => name), ["publish"]);
  assert.notEqual(model.refusal, null);
  act(() => model.clearMessages());
  assert.equal(model.refusal, null);
  assert.equal(model.notice, null);
});

test("the group data access editor lists attribute rows, adds, removes and saves the cleaned rows", () => {
  const { AdminIdentityGroupRlsEditor } = loadStubbed("admin/components/usersTab/AdminIdentityGroupRlsEditor.tsx", []);
  const saved = [];
  const group = { id: "g1", name: "Ops", rls_attributes: [{ key: "tenantid", value: "11" }] };
  const view = create(createElement(AdminIdentityGroupRlsEditor, { group, loading: false, onSave: (rows) => saved.push(rows) }));
  includesAll(text(view.root), ["tenantid=11", "Remove", "Add attribute", "Save attributes", "$group.rls.tenantid"]);
  assert.equal(hostCount(view), 12);
  act(() => button(view, "Add attribute").props.onClick());
  assert.equal(all(view, "input").length, 4);
  act(() => all(view, "input")[2].props.onChange({ target: { value: " region " } }));
  act(() => all(view, "input")[3].props.onChange({ target: { value: "eu" } }));
  assert.equal(all(view, "input")[3].props["aria-label"], "Data access attribute value 2 for Ops");
  act(() => button(view, "Save attributes").props.onClick());
  assert.deepEqual(plain(saved[0]), [{ key: "tenantid", value: "11" }, { key: "region", value: "eu" }]);
  act(() => all(view, "button").filter((node) => text(node) === "Remove")[0].props.onClick());
  act(() => all(view, "button").filter((node) => text(node) === "Remove")[0].props.onClick());
  assert.equal(all(view, "input").length, 2);
  assert.equal(button(view, "Remove").props.disabled, true);
  const empty = create(createElement(AdminIdentityGroupRlsEditor, { group: { id: "g2", name: "X" }, loading: true, onSave() {} }));
  includesAll(text(empty.root), ["No data access attributes", "Saving..."]);
});

const preview = { runs: [{ id: "r1", title: "Build", workspace: "Harbor" }], jobs: [{ id: "j1", folder: "", workspace: "Harbor" }] };

test("the emergency stop panel lists what stops, asks for a reason and a platform confirmation, and stops", async () => {
  const calls = [];
  const api = {
    loadStopPreview: async (id) => { calls.push(["preview", id]); return preview; },
    emergencyStop: async (...args) => { calls.push(["stop", ...args]); return "Stopped 1 run"; },
  };
  const { EmergencyStopPanel } = loadStubbed("admin/components/operations/EmergencyStop.tsx", ["/SidePanel", "/DataTable", "/TimeText"], {},
    { "./operationsApi": api, "/useConfirmAction": { useConfirmAction: () => ({ ask() {}, dialog: null }) } });
  const stopped = [];
  const view = await createAsync(createElement(EmergencyStopPanel, { label: "Stop everything", workspaceId: "", onClose() {},
    onStopped: (result) => stopped.push(result) }));
  const panel = stubs(view, "SidePanel")[0];
  assert.equal(panel.props.title, "Stop everything?");
  assert.equal(panel.props.subtitle, "Emergency stop for every Workspace");
  includesAll(text(view.root), ["Running runs pause", "This stops the whole platform", "Yes, stop the whole platform",
    "Runs that pause", "Device jobs that stop", "Reason (required)", "Cancel", "Stop the whole platform"]);
  assert.deepEqual(stubs(view, "DataTable").map((node) => node.props.testId), ["ops-stop-runs", "ops-stop-jobs"]);
  assert.equal(stubs(view, "DataTable")[1].props.columns[0].render({ folder: "" }), "Device job");
  assert.equal(hostCount(view), 22);
  const confirm = () => byTestId(view, "ops-stop-confirm")[0];
  assert.equal(confirm().props.disabled, true);
  act(() => byTestId(view, "ops-stop-reason")[0].props.onChange({ target: { value: "Incident" } }));
  assert.equal(confirm().props.disabled, true);
  act(() => byTestId(view, "ops-stop-platform-confirm")[0].props.onChange({ target: { checked: true } }));
  assert.equal(confirm().props.disabled, false);
  await act(async () => confirm().props.onClick());
  assert.deepEqual(calls.at(-1), ["stop", "", "Incident"]);
  assert.deepEqual(stopped, ["Stopped 1 run"]);

  const failing = { loadStopPreview: async () => { throw new Error("nope"); }, emergencyStop: async () => { throw new Error("denied"); } };
  const { EmergencyStopPanel: Failing } = loadStubbed("admin/components/operations/EmergencyStop.tsx", ["/SidePanel", "/DataTable", "/TimeText"], {},
    { "./operationsApi": failing, "/useConfirmAction": { useConfirmAction: () => ({ ask() {}, dialog: null }) } });
  const broken = await createAsync(createElement(Failing, { label: "Stop", workspaceId: "w1", onClose() {}, onStopped() {} }));
  includesAll(text(broken.root), ["nope", "Stop everything"]);
  assert.equal(byTestId(broken, "ops-stop-platform-warning").length, 0);
  act(() => byTestId(broken, "ops-stop-reason")[0].props.onChange({ target: { value: "x" } }));
  await act(async () => byTestId(broken, "ops-stop-confirm")[0].props.onClick());
  assert.equal(text(byTestId(broken, "ops-stop-error")[0]), "denied");
});

test("the held-starts notice names the hold, offers Resume or the platform view, and resumes after the confirmation", async () => {
  const asked = [], resumed = [], shown = [];
  const load = (hold) => ({
    loadNewStartsHeld: async () => ({ held: true, hold }),
    resumeNewStarts: async (...args) => { resumed.push(args); return { resumed: true }; },
  });
  const confirm = { "/useConfirmAction": { useConfirmAction: () => ({ ask: (options) => asked.push(options), dialog: null }) } };
  const hold = { scope: "workspace", by: "Ann", at: "2026-01-01T00:00:00Z", reason: "Incident" };
  const { HeldStarts } = loadStubbed("admin/components/operations/EmergencyStop.tsx", ["/TimeText"], {}, { "./operationsApi": load(hold), ...confirm });
  const view = await createAsync(createElement(HeldStarts, { workspaceId: "w1", workspaceName: "Harbor", reloadKey: 0, isPlatformAdmin: false,
    onShowPlatform: () => shown.push(1), onResumed: (result) => shown.push(result) }));
  includesAll(text(view.root), ["New starts are held.", "Incident", "Resume…"]);
  assert.equal(byTestId(view, "ops-held-who").length, 1);
  assert.equal(hostCount(view), 8);
  act(() => byTestId(view, "ops-resume")[0].props.onClick());
  assert.equal(asked[0].title, "Resume new starts in Harbor?");
  assert.equal(asked[0].confirmLabel, "Resume new starts");
  assert.equal(asked[0].field.required, true);
  await act(async () => { await asked[0].run("All clear"); });
  assert.deepEqual(resumed, [["w1", "All clear"]]);
  assert.equal(shown.length, 1);

  const platformHold = { scope: "platform", by: "Bob", at: null, reason: "" };
  const { HeldStarts: Platform } = loadStubbed("admin/components/operations/EmergencyStop.tsx", ["/TimeText"], {},
    { "./operationsApi": load(platformHold), ...confirm });
  const platform = await createAsync(createElement(Platform, { workspaceId: "w1", workspaceName: "Harbor", reloadKey: 0, isPlatformAdmin: true,
    onShowPlatform: () => shown.push("platform"), onResumed() {} }));
  assert.equal(byTestId(platform, "ops-held-platform").length, 1);
  assert.equal(byTestId(platform, "ops-resume").length, 0);
  act(() => byTestId(platform, "ops-show-platform")[0].props.onClick());
  assert.equal(shown.at(-1), "platform");

  const { HeldStarts: Free } = loadStubbed("admin/components/operations/EmergencyStop.tsx", ["/TimeText"], {},
    { "./operationsApi": { loadNewStartsHeld: async () => ({ held: false, hold: null }) }, ...confirm });
  const free = await createAsync(createElement(Free, { workspaceId: "w1", workspaceName: "Harbor", reloadKey: 0, isPlatformAdmin: true,
    onShowPlatform() {}, onResumed() {} }));
  assert.equal(free.toJSON(), null);
});

test("the transcript setting shows the switch and the days, saves either, and reads the server's answer", async () => {
  const saves = [];
  const answer = (enabled, days, canEdit = true) => ({ session_transcripts: { enabled, retention_days: days }, source: "workspace", can_edit: canEdit });
  const api = {
    loadTranscriptSettings: async () => answer(false, 30),
    saveTranscriptSettings: async (id, body) => { saves.push([id, body]); return { ok: true, body: answer(body.enabled ?? false, body.retention_days ?? 30) }; },
  };
  const { WorkspaceTranscriptsCard } = loadStubbed("admin/components/workspaceSettings/WorkspaceTranscriptsCard.tsx", ["/SettingsKit"], {},
    { "/transcriptApi": api });
  const view = await createAsync(createElement(WorkspaceTranscriptsCard, { projectId: "p1" }));
  includesAll(text(view.root), ["Session transcripts", "Keep for (days)", "Set for this Workspace."]);
  assert.equal(stubs(view, "ToggleRow")[0].props.on, false);
  assert.equal(byTestId(view, "transcripts-save").length, 0);
  assert.equal(hostCount(view), 9);
  await act(async () => stubs(view, "ToggleRow")[0].props.onChange(true));
  assert.deepEqual(plain(saves[0]), ["p1", { enabled: true }]);
  includesAll(text(view.root), ["On. Sessions started from now on upload their transcript."]);
  act(() => byTestId(view, "transcripts-retention")[0].props.onChange({ target: { value: "0" } }));
  assert.equal(text(byTestId(view, "transcripts-retention-error")[0]), "Enter whole days from 1 to 3650.");
  assert.equal(byTestId(view, "transcripts-save")[0].props.disabled, true);
  act(() => byTestId(view, "transcripts-retention")[0].props.onChange({ target: { value: "60" } }));
  await act(async () => byTestId(view, "transcripts-save")[0].props.onClick());
  assert.deepEqual(plain(saves[1]), ["p1", { retention_days: 60 }]);
  includesAll(text(view.root), ["Saved. Older transcripts are deleted at the next cleanup."]);

  const { WorkspaceTranscriptsCard: ReadOnly } = loadStubbed("admin/components/workspaceSettings/WorkspaceTranscriptsCard.tsx", ["/SettingsKit"], {},
    { "/transcriptApi": { loadTranscriptSettings: async () => ({ ...answer(true, 7, false), source: "default" }) } });
  const reader = await createAsync(createElement(ReadOnly, { projectId: "p1" }));
  includesAll(text(reader.root), ["Default setting. Read-only: Workspace admins and owners can change it."]);
  const { WorkspaceTranscriptsCard: Broken } = loadStubbed("admin/components/workspaceSettings/WorkspaceTranscriptsCard.tsx", ["/SettingsKit"], {},
    { "/transcriptApi": { loadTranscriptSettings: async () => ({}) } });
  includesAll(text((await createAsync(createElement(Broken, { projectId: "p1" }))).root), ["The server's answer was not a transcript setting."]);
});

const pluginSettings = {
  schema: { required: ["mode"], properties: { mode: { enum: ["a", "b"] }, verbose: { type: "boolean", description: "Talks more" },
    token: { format: "password" }, limit: { type: "integer", title: "Limit (optional)" }, name: { type: "string" } } },
  values: { mode: "a", verbose: true, token: { set: true }, limit: 5 },
};

test("the plugin settings form renders each control, saves the changed values, and shows facts to readers", async () => {
  const saves = [];
  const api = { loadPluginSettings: async () => pluginSettings, savePluginSettings: async (id, values) => { saves.push([id, values]); return pluginSettings; } };
  const { PluginSettingsForm } = loadStubbed("admin/components/plugins/PluginSettingsForm.tsx", [], {}, { "./pluginUiApi": api });
  const view = await createAsync(createElement(PluginSettingsForm, { installId: "i1", canEdit: true }));
  includesAll(text(view.root), ["Mode", "Verbose", "Talks more", "Token (optional)", "Limit (optional)", "Name (optional)", "Save settings"]);
  assert.equal(all(view, "select").length, 1);
  assert.deepEqual(all(view, "input").map((node) => node.props.type), ["checkbox", "password", "number", "text"]);
  assert.equal(all(view, "input")[1].props.placeholder, "Set · type to replace");
  assert.equal(byTestId(view, "plugin-settings-save")[0].props.disabled, true);
  assert.equal(hostCount(view), 22);
  act(() => all(view, "input")[3].props.onChange({ target: { value: "bot" } }));
  assert.equal(byTestId(view, "plugin-settings-save")[0].props.disabled, false);
  await act(async () => all(view, "form")[0].props.onSubmit({ preventDefault() {} }));
  assert.equal(saves.length, 1);
  includesAll(text(view.root), ["Saved."]);

  const { PluginSettingsForm: Reader } = loadStubbed("admin/components/plugins/PluginSettingsForm.tsx", [], {}, { "./pluginUiApi": api });
  const reader = await createAsync(createElement(Reader, { installId: "i1", canEdit: false }));
  assert.deepEqual(all(reader, "dd").map((node) => text(node)), ["a", "Yes", "Set", "5", "Not set"]);
  const { PluginSettingsForm: Empty } = loadStubbed("admin/components/plugins/PluginSettingsForm.tsx", [], {},
    { "./pluginUiApi": { loadPluginSettings: async () => { throw new Error("gone"); } } });
  assert.equal(all(await createAsync(createElement(Empty, { installId: "i1", canEdit: true })), "p")[0].props.role, "alert");
  assert.deepEqual(buttons(reader), []);
});
