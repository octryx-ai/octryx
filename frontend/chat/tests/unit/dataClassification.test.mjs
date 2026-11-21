// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/dataClassification.test.mjs
//
// Simple data classification configuration.
// Workspace settings → Governance → "Data classification" (also an entry of the Agents area's menu, so members reach it read-only):
// one dropdown with the server's levels in order, what the level means here as ✓/✗ lines, the source, and the seat
// switch disabled with its reason when the classification forbids it. Settings → Governance → "Default data
// classification": the Instance default with an explicit apply to unclassified Workspaces. The Agents area links to the
// card when seat sessions are refused because of the classification. The fixtures use made-up level names on purpose:
// the UI must take names and order from the server only. Requests are stubs.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { applyToUnclassifiedLabel, canSaveDraft, classificationLoadErrorText, classificationSaveErrorText, defaultSavedText, defaultSourceText, draftPreview, effectLines, rerankerStatus, readAppliedCount, readInstanceDefault, readLevels, readSeatMode, readWorkspaceClassification, sourceText } from "../../src/admin/components/dataClassification/dataClassificationModel.ts";
import { seatClassificationRefusal, seatSwitchDisabled, seatSwitchNote, seatToggleBlock } from "../../src/admin/components/dataClassification/dataClassificationSeat.ts";
import { resolveProjectSettingsTab } from "../../src/admin/components/projectsTab/projectSettingsSections.ts";
import { ADMIN_AREA_CONFIGS, resolveAdminAreaForTab } from "../../src/admin/config/adminPanelAreas.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const json = (value) => JSON.parse(JSON.stringify(value));

// The 37f7 shape: facts plus the fixed reason of each false fact in `reasons`.
const effects = (reranker, embeddings, seat, reason = null, extra = {}) => ({
  reranker_allowed: reranker, remote_embeddings_allowed: embeddings, seat_mode_allowed: seat,
  reasons: reason ? { seat_mode_allowed: reason } : {}, ...extra,
});
// Made-up names in a made-up order: nothing in the UI may know them.
const LEVELS = [
  { value: "open", label: "Open", description: "Anyone may read it.", effects: effects(true, true, true) },
  { value: "team", label: "Team", description: "Only the team.", effects: effects(true, false, true) },
  { value: "vault", label: "Vault", description: "Locked away.", effects: effects(false, false, false, "seat_classification_too_sensitive") },
];
const WORKSPACE = (overrides = {}) => ({
  effective: "team", source: "workspace", cleared: false, levels: LEVELS, effects: LEVELS[1].effects, seat_mode: "forbidden",
  can_edit: true, instance_default: { classification: "open", state: "configured" }, ...overrides,
});

// ---- registration -------------------------------------------------------------------------------

test("the card lives in Workspace → Rules and the default is a Settings → Governance page", () => {
  // The "classification" section id is an alias of Rules (level + stricter overrides).
  assert.equal(resolveProjectSettingsTab("classification"), "rules");
  // The default level is the Classification header field (Settings › Governance › Classification policy).
  assert.equal(ADMIN_AREA_CONFIGS.admin.groups.some((group) => group.tabs.some((tab) => tab.id === "dataClassification")), false);
  assert.equal(resolveAdminAreaForTab("classificationPolicy"), "admin");
});

test("no level name of the platform is written into the classification UI", () => {
  const files = [
    "admin/components/dataClassification/dataClassificationModel.ts",
    "admin/components/dataClassification/dataClassificationTypes.ts",
    "admin/components/dataClassification/dataClassificationSeat.ts",
    "admin/components/dataClassification/WorkspaceDataClassificationCard.tsx",
    "admin/components/dataClassification/ClassificationHeader.tsx",
    "chat/agents/AgentsSeatRefusal.tsx",
  ];
  for (const file of files) {
    const source = fs.readFileSync(path.join(SRC, file), "utf8");
    for (const level of ["public", "internal", "confidential", "restricted", "secret"]) {
      assert.doesNotMatch(source, new RegExp(`["'\`]${level}["'\`]`), `${file} names ${level}`);
    }
  }
});

// ---- model --------------------------------------------------------------------------------------

test("levels keep the server's order; a plain list and effects per level value are read too", () => {
  assert.deepEqual(readLevels(["b", "a", "b", "", 7]).map((level) => level.value), ["b", "a"], "order kept, duplicates and junk out");
  assert.deepEqual(json(readLevels(["b"])[0]), { value: "b", label: "b", description: "", effects: null });
  const read = readLevels([{ value: "a", rank: 0, effects: effects(false, true, false, "seat_mode_forbidden", {
    governed_models: ["eu-sonnet", ""], reasons: { reranker_allowed: "reranker_not_configured", remote_embeddings_allowed: "embedding_space_local", seat_mode_allowed: "seat_mode_forbidden" } }) }]);
  assert.deepEqual(json(read[0].effects), { rerankerAllowed: false, rerankerState: null, rerankerReason: "reranker_not_configured", remoteEmbeddingsAllowed: true,
    remoteEmbeddingsReason: "embedding_space_local", seatModeAllowed: false, seatModeReason: "seat_mode_forbidden", governedModels: ["eu-sonnet"] });
  assert.deepEqual(effectLines(read[0].effects).map((line) => [line.key, line.allowed, line.detail]), [
    ["reranker", false, "no reranker is configured on this instance"],
    ["embeddings", true, "nothing is sent out"],
    ["seat", false, "this Workspace does not allow them"],
    ["models", true, "eu-sonnet"],
  ]);
  const local = effectLines(read[0].effects).find((line) => line.key === "embeddings");
  assert.deepEqual([local.label, local.words], ["Embeddings for Knowledge", "computed locally"], "local embeddings never read as 'remote … allowed'");
  const denied = readLevels([{ value: "a", effects: effects(false, true, true, null, { governed_models: [], reasons: { reranker_allowed: "data_policy_class_too_low" } }) }]);
  assert.deepEqual(effectLines(denied[0].effects).map((line) => line.detail),
    ["the data policy does not admit this level (data_policy_class_too_low)", "", "", "no gateway model is approved for this level"]);
  assert.equal(readWorkspaceClassification({ effective: "x", levels: [] }), null, "nothing to choose from");
  assert.equal(readWorkspaceClassification(null), null);
  const model = readWorkspaceClassification(WORKSPACE());
  assert.deepEqual(model.levels.map((level) => level.label), ["Open", "Team", "Vault"]);
  assert.equal(model.canEdit, true);
  assert.equal(readWorkspaceClassification(WORKSPACE({ can_edit: "yes" })).canEdit, false, "only an explicit true allows saving");
  assert.equal(readWorkspaceClassification(WORKSPACE({ source: "elsewhere" })).source, "unset");
  assert.equal(readWorkspaceClassification(WORKSPACE()).instanceDefault, "open", "the default is read from {classification, state}");
  // Without top-level facts the effective level's own effects are used.
  assert.equal(readWorkspaceClassification(WORKSPACE({ effects: undefined, effective: "vault" })).effects.rerankerAllowed, false);
  assert.equal(readSeatMode({ seat_mode: "allowed" }), "allowed");
  assert.equal(readSeatMode({ seat_mode: "maybe" }), null);
});

test("source, effects as ✓/✗ lines and the seat switch block come from the server's facts", () => {
  const model = readWorkspaceClassification(WORKSPACE());
  assert.equal(sourceText(model), "Set for this Workspace");
  assert.equal(sourceText(readWorkspaceClassification(WORKSPACE({ source: "instance_default", effective: "open" }))), "Instance default (Open)");
  assert.equal(sourceText(readWorkspaceClassification(WORKSPACE({ source: "unset", effective: null }))), "Not set");
  assert.equal(sourceText(readWorkspaceClassification(WORKSPACE({ source: "unset", effective: null, cleared: true }))), "Not set (cleared on purpose)");
  assert.deepEqual(effectLines(model.effects).map((line) => [line.label, line.allowed]), [
    ["Reranker for Knowledge search", true], ["Remote embeddings for Knowledge", false], ["Claude subscription (seat) sessions", true],
  ]);
  assert.deepEqual(effectLines(readLevels([{ value: "a", effects: { seat_mode_allowed: false } }])[0].effects).map((line) => line.key), ["seat"],
    "an unstated fact gets no line");
  assert.deepEqual(effectLines(readLevels([{ value: "a", effects: { reranker_allowed: true } }])[0].effects).map((line) => line.key), ["reranker"]);
  assert.equal(effectLines(readLevels([LEVELS[2]])[0].effects)[2].detail, "the data classification is too sensitive for them");
  assert.equal(seatToggleBlock(model), null);
  const vault = readWorkspaceClassification(WORKSPACE({ effective: "vault", effects: LEVELS[2].effects }));
  assert.equal(seatToggleBlock(vault), "Not available: the data classification is too sensitive for them.");
  assert.equal(seatClassificationRefusal(vault), "seat_classification_too_sensitive");
  const switchedOff = readWorkspaceClassification(WORKSPACE({ effects: effects(true, true, false, "seat_mode_forbidden") }));
  assert.equal(seatToggleBlock(switchedOff), null, "the Workspace's own switch is what the toggle changes");
  assert.equal(seatClassificationRefusal(switchedOff), null);
  const governed = readWorkspaceClassification(WORKSPACE({ effects: effects(true, true, false, "seat_requires_governed_routing") }));
  assert.equal(seatToggleBlock(governed), "Not available: this Workspace's policy requires governed routing.");
  assert.equal(seatClassificationRefusal(governed), null, "not the classification's doing");
  const unset = readWorkspaceClassification(WORKSPACE({ effective: null, source: "unset", effects: null }));
  assert.equal(seatToggleBlock(unset), "Not available: no data classification is set.");
  // Only turning the switch on is blocked; a stored "allowed" switch stays usable and says it is blocked.
  assert.equal(seatSwitchDisabled(vault, "forbidden"), true);
  assert.equal(seatSwitchDisabled(vault, "allowed"), false);
  assert.equal(seatSwitchDisabled(model, "forbidden"), false);
  assert.equal(seatSwitchDisabled(vault, null), true, "an unknown stored switch is never sent");
  assert.equal(seatSwitchDisabled(model, null), true, "not even where seat is allowed");
  assert.equal(seatSwitchDisabled(readWorkspaceClassification(WORKSPACE({ can_edit: false })), "forbidden"), true, "members never");
  assert.equal(seatSwitchNote(vault, "allowed"), "Stored as allowed, but blocked: the data classification is too sensitive for them. Turning it off is still possible.");
  assert.equal(seatSwitchNote(vault, "forbidden"), "Not available: the data classification is too sensitive for them.");
  assert.equal(seatSwitchNote(unset, "allowed"), "Stored as allowed, but blocked: no data classification is set. Turning it off is still possible.");
  assert.equal(seatSwitchNote(model, "allowed"), null);
  assert.equal(seatClassificationRefusal(unset), "seat_classification_unresolved", "unclassified fails closed");
  assert.equal(seatClassificationRefusal(null), null);
});

test("saving is offered only for a change; the preview says what the chosen level would mean", () => {
  const own = readWorkspaceClassification(WORKSPACE());
  assert.equal(canSaveDraft(own, "team"), false);
  assert.equal(canSaveDraft(own, "vault"), true);
  assert.equal(canSaveDraft(own, ""), true, "clearing an own value");
  const inherited = readWorkspaceClassification(WORKSPACE({ source: "instance_default", effective: "open" }));
  assert.equal(canSaveDraft(inherited, "open"), true, "the default becomes the Workspace's own");
  assert.equal(canSaveDraft(inherited, ""), true, "cleared on purpose, so the default stops filling it in");
  const unset = readWorkspaceClassification(WORKSPACE({ source: "unset", effective: null, effects: null }));
  assert.equal(canSaveDraft(unset, ""), false);
  assert.equal(canSaveDraft(unset, "open"), true);
  assert.equal(draftPreview(own, "team").heading, "What this means here");
  const vault = draftPreview(own, "vault");
  assert.equal(vault.heading, "What this would mean after saving");
  assert.deepEqual(vault.lines.map((line) => line.allowed), [false, false, false]);
  assert.match(draftPreview(own, "").warning, /^Not set: Knowledge search runs without the reranker/);
  assert.match(draftPreview(unset, "").warning, /^Not set:/);
  assert.equal(draftPreview(unset, "").heading, "What this means here");
  assert.equal(draftPreview(readWorkspaceClassification(WORKSPACE({ levels: [{ value: "team" }], effects: null })), "team").unstated, true);
});

test("refusals in words; the Instance default model with the environment bootstrap", () => {
  assert.match(classificationLoadErrorText({ status: 404 }), /does not offer it yet, or you are not a member/);
  assert.equal(classificationLoadErrorText({ status: 403 }), "Only members of this Workspace can see its data classification.");
  assert.equal(classificationLoadErrorText({ status: 500, message: "boom" }), "The data classification could not be loaded: boom.");
  assert.equal(classificationSaveErrorText({ status: 403 }), "Not saved: only Workspace admins and owners can change the classification.");
  assert.equal(classificationSaveErrorText({ status: 422, code: "data_classification_unknown", message: "x" }), "Not saved: the server does not know this level; reload the page.");
  assert.equal(classificationSaveErrorText({ status: 422, code: null, message: "Unprocessable Entity" }), "Not saved: the server refused this value (Unprocessable Entity).");
  assert.equal(classificationSaveErrorText({ status: 409, message: "busy" }), "Not saved: busy.");
  const env = readInstanceDefault({ classification: "team", state: "configured", source: "env", env_value: "team", env_in_effect: true,
    levels: ["open", "team", "vault"], unclassified_count: 4 });
  assert.deepEqual(env.levels.map((level) => level.value), ["open", "team", "vault"], "plain level values, in the server's order");
  assert.equal(env.environmentInEffect, true);
  assert.equal(defaultSourceText(env), "The instance's preset value is in effect (team). Saving here replaces it.");
  assert.equal(defaultSourceText({ ...env, environmentInEffect: false }), "Set here.");
  assert.equal(defaultSourceText({ ...env, environmentInEffect: false, classification: null }), "No Instance default is set: new Workspaces start unclassified.");
  assert.equal(readInstanceDefault({ source: "admin", levels: LEVELS }).unclassifiedWorkspaces, null);
  assert.equal(readInstanceDefault({ source: "env", env_in_effect: "yes", levels: LEVELS }).environmentInEffect, false, "only an explicit true");
  assert.equal(readInstanceDefault({ levels: [] }), null);
  assert.equal(applyToUnclassifiedLabel(4), "Also apply to Workspaces that are not classified yet (4)");
  assert.equal(applyToUnclassifiedLabel(null), "Also apply to Workspaces that are not classified yet");
  assert.equal(readAppliedCount({ applied_count: 3 }), 3);
  assert.equal(readAppliedCount({ applied_count: -1 }), null);
  assert.equal(defaultSavedText(env.levels, "vault", false, null), "Saved: the Instance default is vault.");
  assert.match(defaultSavedText(env.levels, "vault", true, 1), /^Saved: the Instance default is vault\. 1 Workspace was classified; Workspaces with their own value or cleared on purpose were left as they are\.$/);
  assert.match(defaultSavedText(env.levels, "vault", true, null), /The server did not report how many Workspaces were classified/);
});

// ---- rendered -----------------------------------------------------------------------------------

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, FormData, setInterval, clearInterval, setTimeout, CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
      ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

const windowStub = () => ({
  location: { origin: "http://localhost", search: "", href: "http://localhost/chat?area=agents" },
  localStorage: { getItem: () => null, setItem: () => {} },
  history: { state: null, replaceState: () => {} },
  addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => {}, setTimeout: () => 0,
});

function server(answer) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const call = { url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    const { status, body } = answer(call);
    return { ok: status < 400, status, statusText: "", json: async () => body };
  };
  return { fetch, calls };
}
const tick = (ms = 0) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });
const select = (view, id, value) => act(async () => { byTestId(view, id)[0].props.onChange({ target: { value, checked: value } }); });

// A Workspace whose stored state changes with the PUTs, like the server.
// `canLoosen`: the server's `can_loosen`, true only for a platform admin.
function workspaceServer(initial, seat = "forbidden", canLoosen = false) {
  const state = { ...initial };
  let seatMode = seat;
  return server((call) => {
    if (call.url.endsWith("/agent-gateway/seat-mode")) {
      if (call.method === "PUT") seatMode = call.body.seat_mode;
      return { status: 200, body: { seat_mode: seatMode, can_loosen: canLoosen } };
    }
    if (call.method === "PUT") {
      if (call.body.classification === "nope") return { status: 422, body: { detail: { code: "data_classification_unknown" } } };
      const level = LEVELS.find((entry) => entry.value === call.body.classification);
      Object.assign(state, level ? { effective: level.value, source: "workspace", effects: level.effects }
        : { effective: null, source: "unset", cleared: true, effects: null });
      return { status: 200, body: state };
    }
    return { status: 200, body: state };
  });
}

async function renderCard(srv) {
  const { WorkspaceDataClassificationCard } = load("admin/components/dataClassification/WorkspaceDataClassificationCard.tsx", { fetch: srv.fetch, window: windowStub() });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkspaceDataClassificationCard, { projectId: "ws 1" })); });
  await tick();
  return view;
}

test("rendered card (platform admin): levels in the server's order, the preview follows the choice, save sends the level", async () => {
  const srv = workspaceServer(WORKSPACE({ effective: null, source: "unset", effects: null }), "forbidden", true);
  const view = await renderCard(srv);
  try {
    assert.ok(srv.calls[0].url.endsWith("/api/v1/workspaces/ws%201/data-classification"), srv.calls[0].url);
    assert.ok(srv.calls[1].url.endsWith("/api/v1/workspaces/ws%201/agent-gateway/seat-mode"));
    const options = byTestId(view, "classification-select")[0].findAllByType("option");
    assert.deepEqual(options.map((option) => [option.props.value, text(option)]),
      [["", "Not set"], ["open", "Open — Anyone may read it."], ["team", "Team — Only the team."], ["vault", "Vault — Locked away."]]);
    assert.equal(text(byTestId(view, "classification-source")[0]), "Not set");
    assert.match(text(byTestId(view, "classification-warning")[0]), /^Not set: Knowledge search runs without the reranker/);
    assert.equal(byTestId(view, "classification-save")[0].props.disabled, true, "nothing chosen yet");
    assert.equal(byTestId(view, "seat-toggle")[0].props.disabled, true);
    assert.equal(text(byTestId(view, "seat-block")[0]), "Not available: no data classification is set.");

    await select(view, "classification-select", "team");
    assert.equal(text(byTestId(view, "classification-description")[0]), "Only the team.");
    assert.match(text(byTestId(view, "classification-effects")[0]),
      /^What this would mean after saving✓Reranker for Knowledge search allowed✗Remote embeddings for Knowledge not allowed✓Claude subscription \(seat\) sessions allowed$/);
    await act(async () => { byTestId(view, "classification-save")[0].props.onClick(); });
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.deepEqual(put.body, { classification: "team" });
    assert.equal(text(byTestId(view, "classification-message")[0]), "Saved for this Workspace.");
    assert.equal(text(byTestId(view, "classification-source")[0]), "Set for this Workspace");
    assert.match(text(byTestId(view, "classification-effects")[0]), /^What this means here✓Reranker/);

    // The seat switch is now usable and saves the Workspace's own switch.
    assert.equal(byTestId(view, "seat-toggle")[0].props.disabled, false);
    await act(async () => { byTestId(view, "seat-toggle")[0].props.onChange({ target: { checked: true } }); });
    await tick();
    assert.deepEqual(srv.calls.filter((call) => call.method === "PUT").at(-1).body, { seat_mode: "allowed" });
    assert.equal(byTestId(view, "seat-toggle")[0].props.checked, true);
    assert.equal(text(byTestId(view, "seat-message")[0]), "Seat sessions are allowed here.");

    // F5 (judge-1191-1192): on a blocking level the stored "allowed" switch says it is blocked and can still be turned
    // off; once off, turning it on is disabled with the reason.
    await select(view, "classification-select", "vault");
    await act(async () => { byTestId(view, "classification-save")[0].props.onClick(); });
    await tick();
    assert.equal(byTestId(view, "seat-toggle")[0].props.checked, true);
    assert.equal(byTestId(view, "seat-toggle")[0].props.disabled, false, "turning it off stays possible");
    assert.equal(text(byTestId(view, "seat-block")[0]),
      "Stored as allowed, but blocked: the data classification is too sensitive for them. Turning it off is still possible.");
    await act(async () => { byTestId(view, "seat-toggle")[0].props.onChange({ target: { checked: false } }); });
    await tick();
    assert.deepEqual(srv.calls.filter((call) => call.method === "PUT").at(-1).body, { seat_mode: "forbidden" });
    assert.equal(byTestId(view, "seat-toggle")[0].props.checked, false);
    assert.equal(byTestId(view, "seat-toggle")[0].props.disabled, true, "turning it on is blocked");
    assert.equal(text(byTestId(view, "seat-block")[0]), "Not available: the data classification is too sensitive for them.");

    // Clearing sends null and says the default will not refill it.
    await select(view, "classification-select", "");
    await act(async () => { byTestId(view, "classification-save")[0].props.onClick(); });
    await tick();
    assert.deepEqual(srv.calls.filter((call) => call.method === "PUT").at(-1).body, { classification: null });
    assert.match(text(byTestId(view, "classification-message")[0]), /^Saved: not set\. Not set keeps this Workspace unclassified on purpose/);
    assert.equal(text(byTestId(view, "classification-source")[0]), "Not set (cleared on purpose)");
    assert.equal(text(byTestId(view, "seat-block")[0]), "Not available: no data classification is set.");
  } finally { act(() => view.unmount()); }
});

test("The reranker line follows reranker_state; needs_configuration is neutral with its reason, never ✓", () => {
  const reranker = (extra) => effectLines(readLevels([{ value: "a", effects: { remote_embeddings_allowed: true, ...extra } }])[0].effects)
    .find((line) => line.key === "reranker");
  const held = reranker({ reranker_allowed: false, reranker_state: "needs_configuration", reasons: { reranker_allowed: "region_missing" } });
  assert.deepEqual([held.status, held.allowed], ["needs_configuration", false]);
  assert.match(held.detail, /^no AWS region is set for the reranker on this instance; an instance operator sets/);
  // Even a contradicting fact never turns a runtime hold into ✓.
  assert.equal(reranker({ reranker_allowed: true, reranker_state: "needs_configuration" }).status, "needs_configuration");
  assert.equal(reranker({ reranker_allowed: true, reranker_state: "needs_configuration" }).detail, "the reranker needs configuration on this instance");
  assert.equal(reranker({ reranker_allowed: false, reranker_state: "needs_configuration", reasons: { reranker_allowed: "hold_x" } }).detail,
    "the data policy does not admit this level (hold_x)", "an unknown hold code is still named");
  const denied = reranker({ reranker_allowed: false, reranker_state: "denied", reasons: { reranker_allowed: "data_policy_class_insufficient" } });
  assert.deepEqual([denied.status, denied.detail], ["denied", "the data policy does not admit this level (data_policy_class_insufficient)"]);
  assert.equal(reranker({ reranker_allowed: true, reranker_state: "denied" }).status, "denied");
  assert.deepEqual([reranker({ reranker_allowed: true, reranker_state: "ok" }).status, reranker({ reranker_allowed: true, reranker_state: "ok" }).detail], ["allowed", ""]);
  assert.equal(reranker({ reranker_allowed: false, reranker_state: "ok" }).status, "denied", "ok without the allowed fact is not ✓");
  // An answer without reranker_state: the fact decides; an unknown state value is ignored.
  assert.equal(reranker({ reranker_allowed: true }).status, "allowed");
  assert.equal(reranker({ reranker_allowed: true, reranker_state: "maybe" }).status, "allowed");
  assert.equal(readLevels([{ value: "a", effects: { reranker_allowed: true, reranker_state: "maybe" } }])[0].effects.rerankerState, null);
  assert.equal(reranker({ reranker_state: "needs_configuration" }).status, "needs_configuration", "a state alone is shown");
  assert.equal(rerankerStatus({ rerankerAllowed: null, rerankerState: null }), "denied");
});

test("rendered F2: a held reranker shows the neutral mark and the reason, not ✓", async () => {
  const heldLevel = { value: "team", label: "Team", description: "Only the team.", effects: { ...LEVELS[1].effects, reranker_allowed: false,
    reranker_state: "needs_configuration", reasons: { reranker_allowed: "reranker_unknown" } } };
  const srv = workspaceServer(WORKSPACE({ levels: [LEVELS[0], heldLevel, LEVELS[2]], effects: heldLevel.effects }));
  const view = await renderCard(srv);
  try {
    const line = view.root.find((node) => node.type === "li" && node.props["data-status"] === "needs_configuration");
    assert.equal(text(line),
      "–Reranker for Knowledge search needs configuration: the configured reranker is not known; an instance operator corrects the reranker setting");
    assert.equal(line.findByType("span").props.className, "workspace-classification__mark workspace-classification__mark--pending");
    assert.equal(view.root.findAll((node) => node.type === "li" && node.props["data-status"] === "allowed" && /Reranker/.test(text(node))).length, 0);
  } finally { act(() => view.unmount()); }
});

test("rendered card (member): everything read-only, nothing can be sent", async () => {
  const srv = workspaceServer(WORKSPACE({ can_edit: false }), "allowed");
  const view = await renderCard(srv);
  try {
    assert.equal(byTestId(view, "classification-select")[0].props.disabled, true);
    assert.equal(byTestId(view, "classification-save").length, 0);
    assert.equal(text(byTestId(view, "classification-readonly")[0]), "Read-only: Workspace admins and owners can change the classification.");
    assert.equal(byTestId(view, "seat-toggle")[0].props.disabled, true);
    assert.equal(byTestId(view, "seat-toggle")[0].props.checked, true, "the stored switch is still shown");
    assert.equal(srv.calls.filter((call) => call.method !== "GET").length, 0);
  } finally { act(() => view.unmount()); }
});

test("rendered card (Workspace owner, no can_loosen): one hint for the seat block; allowing seats stays locked, forbidding stays open", async () => {
  const off = await renderCard(workspaceServer(WORKSPACE(), "forbidden"));
  try {
    assert.equal(byTestId(off, "seat-toggle")[0].props.disabled, true);
    const hints = byTestId(off, "seat-bound-hint");
    assert.equal(hints.length, 1, "one hint, not one per locked control");
    assert.match(text(hints[0]), /^You can tighten these seat settings\. Only a platform admin can loosen them/);
    assert.equal(byTestId(off, "codex-seat-bound-hint").length, 0);
  } finally { act(() => off.unmount()); }
  const on = await renderCard(workspaceServer(WORKSPACE(), "allowed"));
  try { assert.equal(byTestId(on, "seat-toggle")[0].props.disabled, false, "turning seats off tightens"); }
  finally { act(() => on.unmount()); }
  const admin = await renderCard(workspaceServer(WORKSPACE(), "forbidden", true));
  try {
    assert.equal(byTestId(admin, "seat-bound-hint").length, 0, "no hint with can_loosen");
    assert.equal(byTestId(admin, "seat-toggle")[0].props.disabled, false);
  } finally { act(() => admin.unmount()); }
});

test("rendered card: a refused save shows the server's message; a refused read is explained", async () => {
  const srv = workspaceServer(WORKSPACE({ levels: [...LEVELS, { value: "nope" }] }));
  const view = await renderCard(srv);
  try {
    await select(view, "classification-select", "nope");
    await act(async () => { byTestId(view, "classification-save")[0].props.onClick(); });
    await tick();
    assert.equal(text(byTestId(view, "classification-message")[0]), "Not saved: the server does not know this level; reload the page.");
    assert.equal(byTestId(view, "classification-message")[0].props.role, "alert");
  } finally { act(() => view.unmount()); }
  const missing = await renderCard(server(() => ({ status: 404, body: { detail: "Not Found" } })));
  try {
    assert.match(text(byTestId(missing, "classification-error")[0]), /does not offer it yet, or you are not a member/);
  } finally { act(() => missing.unmount()); }
});

test("rendered Classification header: the default level edits the draft, apply jumps to the Workspaces, engine mode shown", async () => {
  const { ClassificationHeader } = load("admin/components/dataClassification/ClassificationHeader.tsx", { window: windowStub() });
  const picked = [];
  let applied = 0;
  const props = (extra = {}) => ({ levels: LEVELS, defaultLevel: "open", publishedDefault: "open", unclassified: 3, engineMode: "shadow",
    editable: true, busy: false, onDefaultLevel: (level) => picked.push(level), onApplyDefault: () => { applied += 1; }, ...extra });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(ClassificationHeader, props())); });
  try {
    assert.equal(byTestId(view, "classification-default-level")[0].props.value, "open");
    assert.equal(text(byTestId(view, "classification-unclassified")[0]), "3");
    assert.equal(text(byTestId(view, "classification-engine-mode")[0]), "Shadow");
    assert.equal(text(byTestId(view, "classification-apply-default")[0]), "Apply Open");
    await select(view, "classification-default-level", "team");
    await act(async () => { byTestId(view, "classification-apply-default")[0].props.onClick(); });
    assert.deepEqual(picked, ["team"]);
    assert.equal(applied, 1);
    await act(async () => { view.update(createElement(ClassificationHeader, props({ unclassified: 0, editable: false }))); });
    assert.equal(byTestId(view, "classification-apply-default").length, 0, "nothing left to apply");
    assert.equal(byTestId(view, "classification-default-level")[0].props.disabled, true, "read-only while in review");
  } finally { act(() => view.unmount()); }
});

test("rendered Agents area: seat refused by the classification links to the card; nothing for another reason", async () => {
  const run = async (classification) => {
    const srv = server((call) => {
      if (call.url.includes("/agent-gateway/presence")) return { status: 200, body: { items: [] } };
      if (call.url.endsWith("/agent-gateway/seat-mode")) return { status: 200, body: { seat_mode: "allowed" } };
      return { status: 200, body: classification };
    });
    const { AgentsAreaWorkspace } = load("chat/agents/AgentsAreaWorkspace.tsx", { fetch: srv.fetch, window: windowStub(), document: { visibilityState: "visible", addEventListener: () => {}, removeEventListener: () => {} } });
    let view;
    await act(async () => { view = TestRenderer.create(createElement(AgentsAreaWorkspace, {
      projects: [{ id: "ws-1", name: "BRD team" }], fallbackWorkspaceId: "ws-1", pollMs: 10_000 })); });
    await tick();
    return view;
  };
  const refused = await run(WORKSPACE({ effective: "vault", effects: LEVELS[2].effects }));
  try {
    assert.match(text(byTestId(refused, "agents-seat-refused")[0]),
      /^Claude subscription \(seat\) sessions are refused in this Workspace: the data classification is too sensitive for them\. Open Seats & data classification$/);
    await act(async () => { refused.root.find((node) => node.type === "button" && text(node) === "Open Seats & data classification").props.onClick(); });
    await tick();
    assert.equal(byTestId(refused, "classification-card").length, 1);
    // Seat-card finding: the card is back in the Agents menu (Governance), so its entry is the active one.
    assert.deepEqual(refused.root.findAll((node) => node.type === "button" && node.props["aria-current"] === "page").map(text),
      ["Seats & data classification"]);
  } finally { act(() => refused.unmount()); }
  // Refused by the Workspace's own switch, not by the classification: no link.
  const switchedOff = await run(WORKSPACE({ effects: effects(true, true, false, "seat_mode_forbidden") }));
  try {
    assert.equal(byTestId(switchedOff, "agents-clients-empty").length, 1);
    assert.equal(byTestId(switchedOff, "agents-seat-refused").length, 0);
  } finally { act(() => switchedOff.unmount()); }
});
