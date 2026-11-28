// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceContentHandling.test.mjs
//
// Agents → Governance → Policy, "Sensitive content handling": per content kind the action in effect (with a
// "default" marker), the shipped default, the fixed rules, the Workspace's one governance alias, and the per-kind
// change (just the action) for Workspace admins and owners.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ACTION_EXPLANATIONS, ALIAS_IN_USE_TEXT, ALIAS_REQUIRED_TEXT, CONFLICT_TEXT, NO_ALIASES_TEXT, PLATFORM_ONLY_TEXT,
  actionText, aliasBody, aliasProblem, aliasText, choiceBody, choicePreviewLines, choiceProblem, choiceUnchanged,
  contentHandlingLoadErrorText, contentHandlingSaveErrorText, defaultOptionText, effectiveText, initialChoice, readContentHandling,
  readHandlingKind, reroutingKinds, shippedDefaultText, surfaceDefaultLines,
} from "../../src/admin/components/contentSecurity/workspaceContentHandlingModel.ts";
import { act, byTestId, change, click, render, server, text, tick } from "./settingsRenderHarness.mjs";

// The enforcement points (backend `content_security.handling.POINTS`), shortened: what a configured action does at each.
const POINT_LABELS = {
  model_call: "Platform model calls", model_call_direct: "Direct provider driver", model_output: "Model replies",
  gateway_messages: "Coding agents (Anthropic route)", codex_seat: "Codex on a ChatGPT seat",
};
const GATEWAY = new Set(["gateway_messages", "codex_seat"]);
// On the gateway only credentials are acted on (defaults: secrets "refuse", credential assignments "report"), and
// only by refuse or report.
const pointAt = (surface, configured, gatewayDefault = "none") => {
  const action = configured === "default" ? null : configured;
  if (GATEWAY.has(surface)) {
    const value = action ?? gatewayDefault;
    const applies = gatewayDefault !== "none" && ["refuse", "report"].includes(value);
    return { surface, label: POINT_LABELS[surface], configured_action: value,
      action: applies ? value : gatewayDefault, reason: applies ? null : "platform_calls_only" };
  }
  const value = action ?? "mask";
  const rerouting = value === "reroute" || value === "mask_reroute";
  if (rerouting && surface === "model_call_direct") return { surface, label: POINT_LABELS[surface], configured_action: value, action: "refuse", reason: "content_route_unavailable" };
  if (rerouting && surface === "model_output") return { surface, label: POINT_LABELS[surface], configured_action: value, action: "mask", reason: "reroute_masked" };
  return { surface, label: POINT_LABELS[surface], configured_action: value, action: value, reason: null };
};
const points = (configured, gatewayDefault) => Object.keys(POINT_LABELS).map((surface) => pointAt(surface, configured, gatewayDefault));
// The shipped default per path (backend `SHIPPED_DEFAULTS`): only email differs, recorded on gateway routes.
const GATEWAY_SHIPPED = { email: "report" };
const kindEntry = (kind, label, action, defaultAction, isDefault, gatewayDefault = "none") => ({
  kind, label, action, default_action: defaultAction, is_default: isDefault,
  default_actions: [
    { surface: "platform", label: "Platform calls", action: defaultAction },
    { surface: "gateway", label: "Coding agent gateway routes", action: GATEWAY_SHIPPED[kind] ?? defaultAction },
  ],
  reroute_unavailable: [], reroute_masked_at: [],
  surface_defaults: points(isDefault ? "default" : action, gatewayDefault),
  surface_choices: Object.fromEntries(["refuse", "mask", "reroute", "mask_reroute", "report", "default"]
    .map((choice) => [choice, points(choice, gatewayDefault)])),
});
const ANSWER = {
  workspace_id: "ws-1",
  can_edit: true,
  actions: ["refuse", "mask", "reroute", "mask_reroute", "report"],
  governance_alias: "eu-private",
  governance_aliases: [{ alias: "eu-private", label: "EU private model" }, { alias: "ch-private", label: "CH private model" }],
  kinds: [
    kindEntry("email", "Email addresses", "mask", "mask", true),
    kindEntry("internal_ip", "Internal IP addresses", "refuse", "report", false),
    kindEntry("iban", "IBANs", "none", "none", true),
    kindEntry("secrets", "Secrets", "reroute", "mask", false, "refuse"),
    kindEntry("credential_assignment", "Credential assignments", "mask", "mask", true, "report"),
  ],
  // Per point what the fixed rules do there (backend `EnforcementPoint.fixed`): the same rule differs by point.
  fixed: [
    { surface: "model_call", label: "Platform model calls", rules: [
      { rule: "unfinished", action: "withhold", label: "Unfinished part" },
      { rule: "unreadable", action: "refuse", label: "Unreadable content" },
      { rule: "prompt_injection", action: "refuse", label: "Prompt injection in any part" },
    ] },
    { surface: "gateway_messages", label: "Coding agents (Anthropic route)", rules: [
      { rule: "unfinished", action: "refuse", label: "Unfinished examination" },
      { rule: "prompt_injection", action: "refuse", label: "Prompt injection in third-party content" },
    ] },
    { surface: "empty", label: "No rules", rules: [] },
  ],
};
const DATA = readContentHandling(ANSWER);
const kindOf = (kind) => DATA.kinds.find((entry) => entry.kind === kind);

test("the read model keeps the kinds, the default marker, the fixed rules and never offers none", () => {
  const data = readContentHandling({ ...ANSWER, actions: [...ANSWER.actions, "none", "default"] });
  assert.deepEqual(data.actions, ["refuse", "mask", "reroute", "mask_reroute", "report"]);
  assert.equal(data.canEdit, true);
  assert.deepEqual(data.kinds.map((kind) => [kind.kind, kind.isDefault]),
    [["email", true], ["internal_ip", false], ["iban", true], ["secrets", false], ["credential_assignment", true]]);
  assert.equal(data.governanceAlias, "eu-private");
  assert.deepEqual(data.governanceAliases.map((item) => item.alias), ["eu-private", "ch-private"]);
  assert.equal("rerouteAlias" in kindOf("secrets"), false, "a kind carries no alias of its own");
  assert.equal(readContentHandling({ ...ANSWER, governance_alias: null }).governanceAlias, null);
  assert.equal(readContentHandling({ ...ANSWER, governance_alias: "  " }).governanceAlias, null);
  assert.deepEqual(kindOf("email").surfaceDefaults.find((point) => point.surface === "model_call"),
    { surface: "model_call", label: "Platform model calls", configuredAction: "mask", action: "mask", reason: null, conditions: [] });
  assert.deepEqual(Object.keys(kindOf("email").surfaceChoices), ["refuse", "mask", "reroute", "mask_reroute", "report", "default"]);
  const { surface_defaults: _defaults, surface_choices: _choices, ...bare } = ANSWER.kinds[0];
  assert.deepEqual([readHandlingKind(bare).surfaceDefaults, readHandlingKind(bare).surfaceChoices], [[], {}]);
  assert.deepEqual(data.fixed.map((point) => [point.surface, point.rules.map((rule) => `${rule.rule}:${rule.action}`)]), [
    ["model_call", ["unfinished:withhold", "unreadable:refuse", "prompt_injection:refuse"]],
    ["gateway_messages", ["unfinished:refuse", "prompt_injection:refuse"]],
  ], "per point, a point without rules is left out");
  assert.equal(readContentHandling({ kinds: "x" }), null);
  assert.equal(readContentHandling(null), null);
  assert.equal(readHandlingKind({ label: "no kind" }), null);
  assert.equal(readContentHandling({ ...ANSWER, can_edit: "yes" }).canEdit, false);
});

test("action words: none reads as not acted on", () => {
  assert.equal(actionText("none"), "Not acted on");
  assert.equal(actionText("mask_reroute"), "Mask and reroute");
  assert.equal(actionText("report"), "Allow (recorded)");
  assert.deepEqual(ACTION_EXPLANATIONS.map((line) => line.action), ["report", "mask", "refuse", "reroute", "mask_reroute"]);
  assert.match(ACTION_EXPLANATIONS[0].text, /unchanged.*recorded/);
});

test("the starting choice: default while it follows the shipped default, else the stored action", () => {
  assert.equal(initialChoice(kindOf("email")), "default");
  assert.equal(initialChoice(kindOf("internal_ip")), "refuse");
  assert.equal(initialChoice(kindOf("secrets")), "reroute");
  assert.equal(choiceUnchanged("default", kindOf("email")), true);
  assert.equal(choiceUnchanged("reroute", kindOf("secrets")), true);
  assert.equal(choiceUnchanged("mask_reroute", kindOf("secrets")), false);
  assert.equal(choiceUnchanged("default", kindOf("internal_ip")), false);
});

test("the shipped default per path: email is masked on platform calls and recorded on gateway routes", () => {
  assert.equal(shippedDefaultText(kindOf("email")), "Platform calls: Mask; Coding agent gateway routes: Allow (recorded)");
  assert.equal(defaultOptionText(kindOf("email")),
    "Use default (Platform calls: Mask; Coding agent gateway routes: Allow (recorded))");
  assert.equal(shippedDefaultText(kindOf("internal_ip")), "Allow (recorded)", "the same on both paths: one action");
  const { default_actions: _paths, ...older } = ANSWER.kinds[1];
  assert.equal(shippedDefaultText(readHandlingKind(older)), "Allow (recorded)", "without paths: the one default");
});

test("action validation: a rerouting action needs the Workspace's governance alias", () => {
  assert.equal(choiceProblem("mask", DATA), null);
  assert.equal(choiceProblem("default", DATA), null);
  assert.equal(choiceProblem("none", DATA), "Choose an action.");
  assert.equal(choiceProblem("reroute", DATA), null);
  assert.equal(choiceProblem("mask_reroute", DATA), null);
  assert.equal(choiceProblem("reroute", { ...DATA, governanceAlias: null }), ALIAS_REQUIRED_TEXT);
  assert.equal(choiceProblem("mask", { ...DATA, governanceAlias: null }), null);
});

test("payload: a kind sends only its action, the governance alias only the alias", () => {
  assert.deepEqual(choiceBody("reroute"), { action: "reroute" });
  assert.deepEqual(choiceBody("default"), { action: "default" });
  assert.deepEqual(aliasBody("ch-private"), { alias: "ch-private" });
  assert.deepEqual(aliasBody(null), { alias: null });
});

test("governance alias validation: a listed alias, and no clearing while kinds reroute", () => {
  assert.deepEqual(reroutingKinds(DATA).map((kind) => kind.kind), ["secrets"]);
  assert.equal(aliasProblem("ch-private", DATA), null);
  assert.equal(aliasProblem("other", DATA), "Choose a governed alias from the list.");
  assert.match(aliasProblem(null, DATA), /still reroute to it: Secrets\. Set them to another action first/);
  const calm = { ...DATA, kinds: DATA.kinds.filter((kind) => kind.kind !== "secrets") };
  assert.equal(aliasProblem(null, calm), null);
  assert.equal(aliasText(null), "None set: no kind can be rerouted.");
  assert.equal(aliasText("eu-private"), "eu-private");
  assert.equal(effectiveText(kindOf("secrets"), "eu-private"), "Reroute to eu-private");
  assert.equal(effectiveText(kindOf("secrets"), null), "Reroute");
  assert.equal(effectiveText(kindOf("internal_ip"), "eu-private"), "Refuse");
});

test("the effective action per enforcement point: shipped credentials are refused on the gateway, masked elsewhere", () => {
  // Credential assignments are reported on the gateway by default.
  assert.deepEqual(surfaceDefaultLines(kindOf("credential_assignment")),
    ["Elsewhere: Coding agents (Anthropic route): Allow (recorded); Codex on a ChatGPT seat: Allow (recorded)."]);
  // Email is platform calls only: the gateway does not act on it, whatever is saved.
  const savedMask = readHandlingKind(kindEntry("email", "Email addresses", "mask", "mask", false));
  assert.deepEqual(surfaceDefaultLines(savedMask), [`${PLATFORM_ONLY_TEXT} There: Coding agents (Anthropic route): Not acted on; Codex on a ChatGPT seat: Not acted on.`]);
  assert.deepEqual(surfaceDefaultLines(kindOf("email")), [`${PLATFORM_ONLY_TEXT} There: Coding agents (Anthropic route): Not acted on; Codex on a ChatGPT seat: Not acted on.`],
    "the shipped email mask applies to platform calls only");
  // A credential mask is platform calls only too: on the gateway credentials stay refused.
  const credentialMask = readHandlingKind(kindEntry("secrets", "Secrets", "mask", "mask", false, "refuse"));
  assert.deepEqual(surfaceDefaultLines(credentialMask),
    [`${PLATFORM_ONLY_TEXT} There: Coding agents (Anthropic route): Refuse; Codex on a ChatGPT seat: Refuse.`]);
  assert.deepEqual(surfaceDefaultLines(kindOf("iban")).length, 1);
});

test("before saving: what the chosen action does where it differs, the gateway refusal first", () => {
  const email = kindOf("email");
  assert.deepEqual(choicePreviewLines("reroute", email), [
    `${PLATFORM_ONLY_TEXT} There: Coding agents (Anthropic route): Not acted on; Codex on a ChatGPT seat: Not acted on.`,
    "At these places this request is refused with content_route_unavailable instead: Direct provider driver.",
    "At these places the value is masked instead of rerouted: Model replies.",
  ]);
  assert.deepEqual(choicePreviewLines("mask", email), [`${PLATFORM_ONLY_TEXT} There: Coding agents (Anthropic route): Not acted on; Codex on a ChatGPT seat: Not acted on.`]);
  assert.deepEqual(choicePreviewLines("report", email), [`${PLATFORM_ONLY_TEXT} There: Coding agents (Anthropic route): Not acted on; Codex on a ChatGPT seat: Not acted on.`]);
  assert.deepEqual(choicePreviewLines("report", kindOf("secrets")), []);
  assert.deepEqual(choicePreviewLines("default", kindOf("secrets")),
    ["Elsewhere: Coding agents (Anthropic route): Refuse; Codex on a ChatGPT seat: Refuse."]);
  assert.deepEqual(choicePreviewLines("mask", { ...email, surfaceChoices: {} }), []);
  assert.match(PLATFORM_ONLY_TEXT, /^Not acted on at every place/);
});

test("the actual point dispositions: tool results defer, Command safety reviews and denies, the gateway is credentials only", () => {
  const point = (surface, label, configured, action, reason, conditions = []) =>
    ({ surface, label, configured_action: configured, action, reason, conditions });
  const older = { where: "older_history", label: "Earlier turns", action: "mask", reason: "older_history_masked" };
  const anthropic = "Coding agents (Anthropic route)";
  const commands = "Commands (Command safety)";
  const kind = readHandlingKind({
    kind: "internal_ip", label: "Internal IP addresses", action: "mask", default_action: "report", is_default: false,
    surface_defaults: [
      point("model_call", "Platform model calls", "mask", "mask", null),
      point("tool_results", "Tool results", "mask", "none", "deferred_to_model_entrance"),
      point("gateway_messages", anthropic, "mask", "none", "platform_calls_only"),
      point("commands", commands, "mask", "review", "command_review"),
    ],
    surface_choices: {
      refuse: [point("model_call", "Platform model calls", "refuse", "refuse", null, [older]),
        point("tool_results", "Tool results", "refuse", "refuse", null),
        point("commands", commands, "refuse", "deny", "command_denied")],
      report: [point("model_call", "Platform model calls", "report", "report", null), point("commands", commands, "report", "report", null)],
    },
  });
  assert.deepEqual(kind.surfaceChoices.refuse[0].conditions, [older]);
  assert.deepEqual(surfaceDefaultLines(kind), [
    `${PLATFORM_ONLY_TEXT} There: ${anthropic}: Not acted on.`,
    "At these places the content goes on unchanged; the action applies where it next reaches a model: Tool results.",
    `Here the command is sent for review instead (a command cannot be masked): ${commands}.`,
  ]);
  assert.deepEqual(choicePreviewLines("refuse", kind), [
    `Here the command is denied: ${commands}.`,
    "Earlier turns: Mask instead (Platform model calls).",
  ]);
  assert.deepEqual(choicePreviewLines("report", kind), []);
  assert.equal(actionText("deny"), "Deny");
});

test("error texts: each 422 code, 403, the shared 404 and anything else", () => {
  const save = (status, code, message = "") => contentHandlingSaveErrorText(Object.assign(new Error(message), { status, code }));
  assert.equal(save(422, "content_handling_kind_unknown"), "This content kind cannot be configured.");
  assert.equal(save(422, "content_handling_action_invalid"), "This action cannot be chosen for this content kind.");
  assert.equal(save(422, "content_handling_alias_required"), ALIAS_REQUIRED_TEXT);
  assert.match(save(422, "content_handling_alias_unknown"), /not a governed alias/);
  assert.equal(save(409, "content_handling_alias_in_use"), ALIAS_IN_USE_TEXT);
  assert.equal(save(403, null), "Only Workspace admins and owners can change this.");
  assert.equal(save(409, "content_handling_conflict"), CONFLICT_TEXT);
  assert.match(CONFLICT_TEXT, /changed this setting at the same time.*Reload/);
  assert.equal(save(409, "other", "Conflict"), "The setting could not be saved: Conflict.");
  assert.equal(save(404, "project_not_found"), "This Workspace does not exist, or you are not a member of it.");
  assert.equal(save(500, null, "boom"), "The setting could not be saved: boom.");
  assert.equal(save(422, "other", "Unprocessable"), "The setting could not be saved: Unprocessable.");
  assert.equal(contentHandlingLoadErrorText({ status: 404 }), "This Workspace does not exist, or you are not a member of it.");
  assert.equal(contentHandlingLoadErrorText(new Error("down")), "The sensitive content handling could not be loaded: down.");
});

const COMPONENT = "admin/components/contentSecurity/WorkspaceContentHandling.tsx";

test("rendered for a member: the table, the default marker, the fixed rules, read-only", async () => {
  const srv = server(() => ({ status: 200, body: { ...ANSWER, can_edit: false } }));
  const view = await render(COMPONENT, "WorkspaceContentHandling", srv, { workspaceId: "ws-1" });
  try {
    assert.equal(srv.calls[0].url, "/api/v1/workspaces/ws-1/content-handling");
    assert.match(text(byTestId(view, "content-handling-kind-email")[0]), /Email addresses.*Mask.*default.*Mask/);
    assert.match(text(byTestId(view, "content-handling-kind-iban")[0]), /IBANs.*Not acted on.*default.*Not acted on/);
    assert.equal(text(byTestId(view, "content-handling-shipped-email")[0]),
      "Platform calls: Mask; Coding agent gateway routes: Allow (recorded)");
    assert.equal(text(byTestId(view, "content-handling-shipped-secrets")[0]), "Mask");
    assert.match(text(byTestId(view, "content-handling-kind-secrets")[0]), /Reroute to eu-private/);
    assert.equal(text(byTestId(view, "content-handling-governance-alias")[0]), "eu-private");
    assert.deepEqual(byTestId(view, "content-handling-alias"), [], "a member cannot change the alias");
    assert.equal(byTestId(view, "content-handling-default").length, 3);
    assert.equal(text(byTestId(view, "content-handling-surfaces-credential_assignment")[0]),
      "Elsewhere: Coding agents (Anthropic route): Allow (recorded); Codex on a ChatGPT seat: Allow (recorded).");
    assert.match(text(byTestId(view, "content-handling-surfaces-email")[0]), /Coding agents \(Anthropic route\): Not acted on/);
    const fixed = text(byTestId(view, "content-handling-fixed")[0]);
    assert.match(fixed, /Platform model calls.*Unfinished part: Withhold, always.*Prompt injection in any part: Refuse, always/);
    assert.match(fixed, /Coding agents \(Anthropic route\).*Unfinished examination: Refuse, always/);
    assert.match(text(byTestId(view, "content-handling-read-only")[0]), /Workspace admins and owners/);
    assert.deepEqual(byTestId(view, "content-handling-edit-email"), []);
  } finally { act(() => view.unmount()); }
});

test("rendered for an admin: one alias selector, per kind only the action, the refused places named", async () => {
  const saved = kindEntry("email", "Email addresses", "reroute", "mask", false);
  const srv = server((call) => (call.method === "PUT" ? { status: 200, body: saved } : { status: 200, body: ANSWER }));
  const view = await render(COMPONENT, "WorkspaceContentHandling", srv, { workspaceId: "ws-1" });
  try {
    const saveButton = () => byTestId(view, "content-handling-save-email")[0];
    const options = byTestId(view, "content-handling-action-email")[0].findAllByType("option").map((option) => option.props.value);
    assert.deepEqual(options, ["default", "refuse", "mask", "reroute", "mask_reroute", "report"]);
    assert.equal(saveButton().props.disabled, true, "nothing changed yet");
    assert.deepEqual(byTestId(view, "content-handling-alias-email"), [], "no per-kind alias");
    assert.equal(byTestId(view, "content-handling-alias").length, 1);
    await change(view, "content-handling-action-email", "reroute");
    const preview = text(byTestId(view, "content-handling-preview-email")[0]);
    assert.match(preview, /Not acted on at every place/);
    assert.match(preview, /content_route_unavailable instead: Direct provider driver/);
    assert.match(preview, /masked instead of rerouted: Model replies/);
    assert.equal(saveButton().props.disabled, false);
    await click(view, "content-handling-save-email");
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.equal(put.url, "/api/v1/workspaces/ws-1/content-handling/email");
    assert.deepEqual(put.body, { action: "reroute" });
    assert.match(text(byTestId(view, "content-handling-kind-email")[0]), /Reroute to eu-private/);
    assert.equal(text(byTestId(view, "content-handling-message-email")[0]), "Saved.");
  } finally { act(() => view.unmount()); }
});

test("rendered for an admin without governed aliases: no alias can be set and reroute cannot be saved", async () => {
  const kinds = ANSWER.kinds.filter((kind) => kind.kind !== "secrets");
  const srv = server(() => ({ status: 200, body: { ...ANSWER, governance_alias: null, governance_aliases: [], kinds } }));
  const view = await render(COMPONENT, "WorkspaceContentHandling", srv, { workspaceId: "ws-1" });
  try {
    assert.equal(text(byTestId(view, "content-handling-no-aliases")[0]), NO_ALIASES_TEXT);
    assert.deepEqual(byTestId(view, "content-handling-alias"), []);
    await change(view, "content-handling-action-email", "mask_reroute");
    assert.equal(text(byTestId(view, "content-handling-problem-email")[0]), ALIAS_REQUIRED_TEXT);
    assert.equal(byTestId(view, "content-handling-save-email")[0].props.disabled, true);
  } finally { act(() => view.unmount()); }
});

test("rendered for an admin: the governance alias is changed once for the Workspace and not cleared while kinds reroute", async () => {
  const srv = server((call) => (call.method === "PUT"
    ? { status: 200, body: { workspace_id: "ws-1", governance_alias: "ch-private" } } : { status: 200, body: ANSWER }));
  const view = await render(COMPONENT, "WorkspaceContentHandling", srv, { workspaceId: "ws-1" });
  try {
    const saveButton = () => byTestId(view, "content-handling-alias-save")[0];
    const options = byTestId(view, "content-handling-alias")[0].findAllByType("option").map((option) => option.props.value);
    assert.deepEqual(options, ["", "eu-private", "ch-private"]);
    assert.equal(saveButton().props.disabled, true, "nothing changed yet");
    await change(view, "content-handling-alias", "");
    assert.match(text(byTestId(view, "content-handling-alias-problem")[0]), /still reroute to it: Secrets/);
    assert.equal(saveButton().props.disabled, true);
    await change(view, "content-handling-alias", "ch-private");
    assert.deepEqual(byTestId(view, "content-handling-alias-problem"), []);
    await click(view, "content-handling-alias-save");
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.equal(put.url, "/api/v1/workspaces/ws-1/content-handling/governance-alias");
    assert.deepEqual(put.body, { alias: "ch-private" });
    assert.equal(text(byTestId(view, "content-handling-governance-alias")[0]), "ch-private");
    assert.match(text(byTestId(view, "content-handling-kind-secrets")[0]), /Reroute to ch-private/);
    assert.equal(text(byTestId(view, "content-handling-alias-message")[0]), "Saved.");
  } finally { act(() => view.unmount()); }
});

test("rendered: clearing the alias refused by the server shows why", async () => {
  const kinds = ANSWER.kinds.filter((kind) => kind.kind !== "secrets");
  const srv = server((call) => (call.method === "PUT"
    ? { status: 409, body: { detail: { code: "content_handling_alias_in_use", kinds: ["email"] } } }
    : { status: 200, body: { ...ANSWER, kinds } }));
  const view = await render(COMPONENT, "WorkspaceContentHandling", srv, { workspaceId: "ws-1" });
  try {
    await change(view, "content-handling-alias", "");
    await click(view, "content-handling-alias-save");
    await tick();
    assert.deepEqual(srv.calls.find((call) => call.method === "PUT").body, { alias: null });
    assert.equal(text(byTestId(view, "content-handling-alias-message")[0]), ALIAS_IN_USE_TEXT);
    assert.equal(text(byTestId(view, "content-handling-governance-alias")[0]), "eu-private");
  } finally { act(() => view.unmount()); }
});

test("rendered: a save that lost a concurrent edit says so and nothing is replaced", async () => {
  const srv = server((call) => (call.method === "PUT"
    ? { status: 409, body: { detail: { code: "content_handling_conflict", message: "changed meanwhile" } } } : { status: 200, body: ANSWER }));
  const view = await render(COMPONENT, "WorkspaceContentHandling", srv, { workspaceId: "ws-1" });
  try {
    await change(view, "content-handling-action-email", "mask");
    assert.match(text(byTestId(view, "content-handling-preview-email")[0]), /Not acted on at every place/);
    await click(view, "content-handling-save-email");
    await tick();
    assert.equal(text(byTestId(view, "content-handling-message-email")[0]), CONFLICT_TEXT);
    assert.match(text(byTestId(view, "content-handling-kind-email")[0]), /Email addresses.*Mask.*default/);
  } finally { act(() => view.unmount()); }
});

test("rendered: a refused save shows its words; a non-member gets the shared 404", async () => {
  const srv = server((call) => (call.method === "PUT"
    ? { status: 403, body: { detail: { code: "content_handling_forbidden", message: "Forbidden" } } } : { status: 200, body: ANSWER }));
  const view = await render(COMPONENT, "WorkspaceContentHandling", srv, { workspaceId: "ws-1" });
  try {
    await change(view, "content-handling-action-email", "refuse");
    await click(view, "content-handling-save-email");
    await tick();
    assert.equal(text(byTestId(view, "content-handling-message-email")[0]), "Only Workspace admins and owners can change this.");
  } finally { act(() => view.unmount()); }
  const missing = server(() => ({ status: 404, body: { detail: { code: "project_not_found", message: "Not found" } } }));
  const gone = await render(COMPONENT, "WorkspaceContentHandling", missing, { workspaceId: "ws-x" });
  try {
    assert.equal(text(byTestId(gone, "content-handling-error")[0]), "This Workspace does not exist, or you are not a member of it.");
  } finally { act(() => gone.unmount()); }
});
