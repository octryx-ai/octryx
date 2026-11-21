// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/policyBuilder.test.mjs
//
// The guided policy builder: the structured model, block availability from the catalog
// (hidden / disabled with the G7 reason), templates with placeholders, the live server preview, policy-level saves
// with If-Match (new, edit, duplicate, remove, conflict), the per-policy Cedar editor and "Edit as Cedar…".

import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  actionsWithoutUser, blankModel, blockState, commandSplit, duplicateModel, fieldValue, fromTemplate, missingPlaceholders, readModel,
  saveBody, slug, startStep, usesWho, withField,
} from "../../src/admin/components/policyEngine/policyBuilderModel.ts";
import { readCatalog } from "../../src/admin/components/policyEngine/policyCatalogModel.ts";
import { actionBreakdown, exampleCase, lineDiff, readDraftImpact, readImpact, readReview } from "../../src/admin/components/policyEngine/policyLifecycleModel.ts";
import { CATALOG, STATUS, act, byTestId, change, click, load, server, text, tick } from "./policyEngineHarness.mjs";

// The served catalog resolves the block scopes ("all", "classified"), like catalog.catalog_payload().
const POINTS = Object.fromEntries(CATALOG.enforcement_points.map((point) => [point.id, point]));
const SERVED = {
  ...CATALOG,
  actions: CATALOG.actions.map((action) => ({ ...action, point_label: POINTS[action.point].label, point_when: POINTS[action.point].checked_when, carries_user: POINTS[action.point].carries_user,
    carries_classification: POINTS[action.point].carries_classification })),
  condition_blocks: CATALOG.condition_blocks.map((block) => ({ ...block, actions: block.actions === "all" ? CATALOG.actions.map((action) => action.id)
    : block.actions === "classified" ? CATALOG.actions.filter((action) => POINTS[action.point].carries_classification).map((action) => action.id) : block.actions })),
  connector_families: ["servicenow", "jira", "confluence", "kubernetes", "aws", "bitbucket"],
};
const catalog = readCatalog(SERVED);
const template = (id) => catalog.templates.find((item) => item.id === id);

// ---- model -----------------------------------------------------------------------------------------------------

test("model: defaults, templates, duplicates and field access", () => {
  const model = readModel({ id: "x", actions: ["run_command", 3], who: { mode: "roles", items: ["sre"] }, what: { paths: "nope" } });
  assert.deepEqual(model.actions, ["run_command"]);
  assert.deepEqual(model.who, { mode: "roles", items: ["sre"], except_admins: false, session_profile: "", session_client: "" });
  assert.deepEqual(model.what.paths, []);
  assert.deepEqual(Object.keys(model), Object.keys(blankModel()), "exactly the server's fields");
  assert.equal(slug("Prod  ServiceNow → read-only!"), "prod-servicenow-read-only");
  const fromTpl = fromTemplate(template("kubectl-non-prod-context-only"));
  assert.equal(fromTpl.template, "kubectl-non-prod-context-only");
  assert.equal(fromTpl.id, "kubectl-restarts-only-in-non-prod");
  assert.deepEqual(fromTpl.what.arguments, ["rollout", "restart"]);
  assert.deepEqual(duplicateModel(fromTpl, [fromTpl.id, `${fromTpl.id}-copy`]).id, `${fromTpl.id}-copy-2`);
  assert.equal(duplicateModel(fromTpl, []).name, "kubectl restarts only in non-prod (copy)");
  assert.deepEqual(fieldValue(withField(fromTpl, "where.connections", ["c-1"]), "where.connections"), ["c-1"]);
  assert.deepEqual(saveBody(fromTpl, true, ""), { model: fromTpl, create: true });
});

test("model: template placeholders are the required inputs and pick the starting step", () => {
  const prod = fromTemplate(template("prod-connection-read-only"));
  assert.deepEqual(missingPlaceholders(prod, catalog).map((item) => item.field), ["where.connections"]);
  assert.equal(startStep(prod, catalog), "where");
  assert.deepEqual(missingPlaceholders(withField(prod, "where.connections", ["c-1"]), catalog), []);
  assert.equal(startStep(withField(prod, "where.connections", ["c-1"]), catalog), "check");
  assert.equal(startStep(fromTemplate(template("kubectl-non-prod-context-only")), catalog), "who");
  assert.equal(startStep(fromTemplate(template("block-secret-files")), catalog), "check");
  assert.equal(startStep(fromTemplate(template("confidential-approved-model-only")), catalog), "what");
});

test("model: blocks are available, disabled with the reason, or hidden — from the catalog", () => {
  assert.deepEqual(blockState(catalog, "where.connection", ["write_connector", "read_connector"]), { state: "available", reason: "" });
  assert.equal(blockState(catalog, "where.connection", ["write_connector", "call_model"]).state, "hidden");
  assert.equal(blockState(catalog, "where.classification_at_least", ["run_command"]).state, "available", "G7");
  const noClass = readCatalog({ ...SERVED, actions: SERVED.actions.map((action) => (action.point === "gateway_tool_check" ? { ...action, carries_classification: false } : action)),
    condition_blocks: SERVED.condition_blocks.map((block) => (block.classification_bound ? { ...block, actions: block.actions.filter((id) => !["run_command", "read_path", "write_path"].includes(id)) } : block)) });
  const level = blockState(noClass, "where.classification_at_least", ["run_command"]);
  assert.equal(level.state, "disabled");
  assert.match(level.reason, /Run a shell command.*does not know the Workspace classification/);
  assert.equal(blockState(catalog, "where.classification_at_least", ["call_model"]).state, "available");
  assert.equal(blockState(catalog, "what.program", []).state, "hidden");
  assert.deepEqual(actionsWithoutUser(catalog, ["run_command", "write_connector"]), [], "every point carries the user");
  const blind = readCatalog({ ...SERVED, actions: SERVED.actions.map((action) => (action.id === "write_connector" ? { ...action, carries_user: false } : action)) });
  assert.deepEqual(actionsWithoutUser(blind, ["run_command", "write_connector"]), ["write_connector"]);
  assert.equal(usesWho(blankModel()), false);
  assert.equal(usesWho({ ...blankModel(), who: { ...blankModel().who, except_admins: true } }), true);
});

test("model: the command split preview marks what the policy matches", () => {
  const model = { ...blankModel(), what: { ...blankModel().what, programs: ["kubectl"], arguments: ["delete"] } };
  assert.deepEqual(commandSplit("/usr/bin/kubectl --context ctx delete pod x", model).map((part) => [part.token, part.hit]), [
    ["kubectl", true], ["--context", false], ["ctx", false], ["delete", true], ["pod", false], ["x", false],
  ]);
});

// ---- rendered --------------------------------------------------------------------------------------------------

const seg = (value, emphasis = null) => ({ text: value, emphasis });
const PROD_MODEL = { ...blankModel(), id: "prod-read-only", name: "Production read-only", actions: ["write_connector"], where: { ...blankModel().where, connections: ["c-1"] } };
const PROD_TEXT = '@id("prod-read-only")\n@name("Production read-only")\n@builder("1")\nforbid (principal, action == Action::"write_connector", resource)\nwhen { context.connections.containsAny(["c-1"]) };';
const HAND_TEXT = '@id("contractors-jira")\nforbid (principal in Group::"contractors", action == Action::"write_connector", resource);';
const ITEM = (id, overrides) => ({ id, name: id, description: "", source: "hand_written", editable: true, effect: "forbid", actions: ["write_connector"],
  groups: ["Connectors & tools"], points: ["Tool admission (chat & MCP)"], text: "", digest: `d-${id}`, sentence: [seg("Block", "verb")], scope: "All Workspaces",
  references: { entities: {}, connections: [] }, warnings: [], change: "unchanged", last_changed: null, model: null, ...overrides });

const IMPACT = (policyId) => ({
  workspace: { id: "ws-1", name: "Claims", classification: "confidential" }, notes: ["Nobody matches the who-part yet; the examples run without a user."],
  policy_source: "version 3 with this policy",
  examples: [
    { name: "add_jira_comment is blocked", kind: "block", expected: "deny", request: { workspace_id: "ws-1", action: "write_connector", resource: { tool: "add_jira_comment" } },
      answer: { decision: "deny", determining: [policyId], by_this_policy: true, as_expected: true, error: null } },
    { name: "jira_search on another tool", kind: "block", expected: "deny", request: { workspace_id: "ws-1", action: "write_connector", resource: { tool: "x" } },
      answer: { decision: "allow", determining: ["platform:tool-permit", "workspace:ws-1:tool-rule:kubectl-requires-context"], by_this_policy: false, as_expected: false, error: null } },
    { name: "broken", kind: "block", expected: "deny", request: {}, answer: { decision: "error", determining: [], by_this_policy: false, as_expected: false, error: "policy_bench_request_invalid" } },
    { name: "get_jira_ticket (a read) stays allowed", kind: "control", expected: "allow", request: { workspace_id: "ws-1", action: "read_connector", resource: { tool: "get_jira_ticket" } },
      answer: { decision: "allow", determining: ["platform:tool-permit"], by_this_policy: false, as_expected: true, error: null } },
  ],
  cases: { results: [{ id: "t1", name: "old case", expected: "allow", actual: "deny", passed: false, determining: [policyId, "platform:tool-permit"] }] },
});

function builderServer({ state = "draft", items = null, conflict = false, catalog: served = SERVED } = {}) {
  const target = state === "draft" ? { version: 3, digest: "sha256:3", creates_draft: false } : state === "published" ? { version: 2, digest: "sha256:2", creates_draft: true } : null;
  const listed = items ?? [ITEM("prod-read-only", { source: "builder", model: PROD_MODEL, text: PROD_TEXT }), ITEM("contractors-jira", { text: HAND_TEXT })];
  return server((call) => {
    const url = call.url.replace("/api/v1/admin/policy-engine", "");
    if (url === "/status") return { status: 200, body: STATUS() };
    if (url === "/catalog") return { status: 200, body: served };
    if (url === "/catalog/entities") return { status: 200, body: {
      workspaces: [{ id: "ws-1", name: "Claims", classification: "confidential" }],
      users: [{ id: "u-1", username: "ada" }], roles: [{ name: "sre", member_count: 3 }], groups: [{ name: "contractors", member_count: 9 }],
      named_connections: [{ id: "c-1", name: "primary", connector: "servicenow", scope: "global" }],
      tools: [{ name: "servicenow_update_record", connector_family: "servicenow" }, { name: "web_search", connector_family: null }],
      model_aliases: [{ alias: "model-a", data_policy_class: "internal" }],
      connector_families: [{ id: "servicenow", label: "ServiceNow" }, { id: "jira", label: "Jira" }] } };
    if (url.startsWith("/policies")) return { status: 200, body: { version: state === "none" ? null : { version: state === "published" ? 2 : 3, state: state === "none" ? "draft" : state, digest: "sha256:x" },
      published_version: 2, items: listed, changes: {}, edit_target: state === "none" ? { version: 0, digest: "sha256:empty", creates_draft: true } : target } };
    if (url === "/policy-sets" && call.method === "GET") return { status: 200, body: { items: [] } };
    if (url === "/schema") return { status: 200, body: { schema: "" } };
    if (url === "/policy-builder/render") {
      const model = call.body.model;
      return { status: 200, body: { valid: true, issues: [], text: `@id("${model.id}")\n@builder("1")\nforbid (principal, action == Action::"${model.actions[0]}", resource);`,
        sentence: [seg("Block", "verb"), seg(" "), seg("everyone", "value"), seg(" from "), seg(model.actions.join(", "), "value"), seg(".")], scope: "All Workspaces",
        warnings: model.who.mode === "roles" ? [{ code: "who_not_effective", message: "Who-conditions are not effective yet." }] : [] } };
    }
    if (url === "/validate") return { status: 200, body: { valid: !call.body.policies.includes("permit") } };
    if (url === "/test-bench/generate") return { status: 200, body: IMPACT(call.body.model.id) };
    if (/^\/policy-sets\/3\/impact/.test(url)) return { status: 200, body: { version: 3, hours: 24, total: 4, policies: {
      "prod-read-only": { count: 4, points: { tool_admission: 4 }, actions: { write_connector: 4 }, principals: 1, samples: [] } } } };
    if (url === "/tests" && call.method === "POST") return { status: 201, body: { id: "case" } };
    if (/^\/policy-sets\/\d+\/policies\//.test(url) && (call.method === "PUT" || call.method === "DELETE")) {
      if (conflict) return { status: 409, body: { detail: { code: "policy_set_draft_conflict", digest: "sha256:new" } } };
      return { status: 200, body: { version: { version: 3, state: "draft" }, policy: null } };
    }
    if (/^\/policy-sets\/\d+\/policies\//.test(url)) return { status: 200, body: { history: [] } };
    if (/^\/policy-sets\/\d+$/.test(url)) return { status: 200, body: { version: Number(url.split("/")[2]), state, digest: "sha256:x", policies: "", test_report: { results: [] } } };
    if (url.startsWith("/decisions")) return { status: 200, body: { items: [], total: 0 } };
    return { status: 404, body: { detail: "nope" } };
  });
}

const StubEditor = ({ value, onChange }) => createElement("textarea", { "data-testid": "stub-editor", value, onChange: (event) => onChange(event.target.value) });

async function renderPage(srv) {
  const { AdminCedarPolicies } = load("admin/components/policyEngine/AdminCedarPolicies.tsx", { fetch: srv.fetch, window: undefined });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminCedarPolicies, { editor: StubEditor, search: "", previewDelay: 0 })); });
  for (let index = 0; index < 4; index += 1) await tick();
  return view;
}
const settle = async () => { await tick(); await tick(); };
const chip = (view, id, value) => byTestId(view, `${id}-chip`).find((node) => node.props["data-value"] === value);
const press = (node) => act(async () => { node.props.onClick(); });
const lastRender = (srv) => srv.calls.filter((call) => call.url.endsWith("/policy-builder/render")).at(-1)?.body.model;
const puts = (srv) => srv.calls.filter((call) => call.method === "PUT" && call.url.includes("/policies/"));

test("builder: a new policy — name → @id, action cards, Who, Where with names, live preview, save with If-Match", async () => {
  const srv = builderServer();
  const view = await renderPage(srv);
  await click(view, "policy-new");
  assert.equal(byTestId(view, "policy-builder").length, 1);
  assert.match(text(byTestId(view, "builder-target")[0]), /Saves into draft v3/);
  assert.match(text(byTestId(view, "builder-step-hint")[0]), /Name it the way people will search/);
  await change(view, "builder-name", "Prod ServiceNow read-only");
  assert.equal(byTestId(view, "builder-save")[0].props.disabled, true, "no action yet");
  await click(view, "builder-step-what");
  assert.equal(byTestId(view, "builder-no-action").length, 1);
  const subtitle = byTestId(view, "builder-action-run_command")[0].findAll((node) => node.type === "small")[0];
  assert.equal(subtitle.children.join(""), "Checked before a coding agent runs a command or reads or writes a file", "plain language, not the point id");
  assert.equal(subtitle.props.title, "Enforcement point: Coding-agent tool check");
  assert.equal(byTestId(view, "builder-action-write_connector")[0].findAll((node) => node.type === "small")[0].children.join(""), "Checked when an agent uses a tool (chat & MCP)");
  await click(view, "builder-action-write_connector");
  await settle();
  assert.equal(byTestId(view, "builder-families").length, 1, "connector families for connector actions");
  assert.equal(byTestId(view, "builder-programs").length, 0, "command blocks stay hidden");
  await press(chip(view, "builder-families", "servicenow"));
  assert.deepEqual(chip(view, "builder-tools", "servicenow_update_record") ? ["ok"] : [], ["ok"], "tools filtered by the connector");
  assert.equal(chip(view, "builder-tools", "web_search"), undefined);
  await click(view, "builder-step-who");
  await click(view, "builder-who-roles");
  await press(chip(view, "builder-who-items", "sre"));
  assert.match(text(chip(view, "builder-who-items", "sre")), /✓ sre · 3/);
  assert.equal(byTestId(view, "builder-who-warning").length, 0, "tool admission carries the user");
  await click(view, "builder-step-where");
  assert.match(text(chip(view, "builder-connections", "c-1")), /primary · servicenow · Global/);
  await press(chip(view, "builder-connections", "c-1"));
  await settle();
  const sent = lastRender(srv);
  assert.equal(sent.id, "prod-servicenow-read-only");
  assert.deepEqual([sent.actions, sent.who.items, sent.what.families, sent.where.connections], [["write_connector"], ["sre"], ["servicenow"], ["c-1"]]);
  assert.match(text(byTestId(view, "builder-sentence")[0]), /^Block everyone from write_connector\.$/);
  assert.equal(byTestId(view, "builder-warning").length, 1, "the server's warnings are shown");
  assert.match(text(byTestId(view, "builder-cedar")[0]), /@id\("prod-servicenow-read-only"\)/);
  await click(view, "builder-save");
  await settle();
  const [saved] = puts(srv);
  assert.equal(saved.url, "/api/v1/admin/policy-engine/policy-sets/3/policies/prod-servicenow-read-only");
  assert.equal(saved.headers["If-Match"], "sha256:3");
  assert.equal(saved.body.create, true);
  assert.deepEqual(saved.body.model.where.connections, ["c-1"]);
  assert.equal(byTestId(view, "policy-builder").length, 0, "back to the list");
  assert.match(text(byTestId(view, "cedar-message")[0]), /Saved "Prod ServiceNow read-only" to the draft/);
});

test("builder: a who-condition on a check that does not carry the user is flagged (catalog-driven)", async () => {
  const blindCatalog = { ...SERVED, actions: SERVED.actions.map((action) => (action.id === "use_seat" ? { ...action, carries_user: false } : action)) };
  const srv = builderServer({ catalog: blindCatalog });
  const view = await renderPage(srv);
  await click(view, "policy-new");
  await click(view, "builder-step-what");
  await click(view, "builder-action-use_seat");
  await click(view, "builder-step-who");
  await click(view, "builder-who-roles");
  await press(chip(view, "builder-who-items", "sre"));
  assert.match(text(byTestId(view, "builder-who-warning")[0]), /Not effective yet for Use a personal seat/);
});

test("builder: classification is disabled with the reason when a check lacks it (catalog-driven; none since G7)", async () => {
  const srv = builderServer({ catalog: { ...SERVED, actions: SERVED.actions.map((action) => (action.point === "gateway_tool_check" ? { ...action, carries_classification: false } : action)),
    condition_blocks: SERVED.condition_blocks.map((block) => (block.classification_bound ? { ...block, actions: block.actions.filter((id) => !["run_command", "read_path", "write_path"].includes(id)) } : block)) } });
  const view = await renderPage(srv);
  await click(view, "policy-new");
  await click(view, "builder-step-what");
  await click(view, "builder-action-run_command");
  assert.equal(byTestId(view, "builder-programs").length, 1);
  assert.equal(byTestId(view, "builder-families").length, 0);
  await change(view, "builder-programs-input", "kubectl");
  await click(view, "builder-programs-add");
  assert.deepEqual(byTestId(view, "builder-command-split")[0].findAll((node) => node.props.className === "policies__split-hit").map(text), ["program: kubectl"]);
  await click(view, "builder-step-where");
  assert.equal(byTestId(view, "builder-level")[0].props.disabled, true);
  assert.match(text(byTestId(view, "builder-level-disabled")[0]), /does not know the Workspace classification/);
  assert.equal(byTestId(view, "builder-connections").length, 0);
});

test("builder: with the real catalog, coding-agent actions can be narrowed by classification (G7)", async () => {
  const srv = builderServer();
  const view = await renderPage(srv);
  await click(view, "policy-new");
  await click(view, "builder-step-what");
  await click(view, "builder-action-run_command");
  await click(view, "builder-step-where");
  assert.equal(byTestId(view, "builder-level")[0].props.disabled, false);
  assert.equal(byTestId(view, "builder-level-disabled").length, 0);
});

test("templates: the gallery opens the builder pre-filled; placeholders are required before saving", async () => {
  const srv = builderServer();
  const view = await renderPage(srv);
  await click(view, "policies-tab-templates");
  assert.equal(byTestId(view, "policy-template").length, 12);
  await click(view, "policy-template-use-prod-connection-read-only");
  await settle();
  assert.equal(byTestId(view, "builder-pane-where").length, 1, "opens on the step with the missing input");
  assert.match(text(byTestId(view, "builder-placeholder")[0]), /Required: Production connection/);
  assert.equal(byTestId(view, "builder-save")[0].props.disabled, true);
  assert.match(byTestId(view, "builder-save")[0].props.title, /Fill in: Production connection/);
  await press(chip(view, "builder-connections", "c-1"));
  await settle();
  assert.equal(byTestId(view, "builder-placeholder").length, 0);
  assert.equal(byTestId(view, "builder-save")[0].props.disabled, false);
  assert.equal(lastRender(srv).template, "prod-connection-read-only");
});

test("edit, duplicate and remove: builder policies re-open in the builder, hand-written ones in the Cedar editor", async () => {
  const srv = builderServer();
  const view = await renderPage(srv);
  await act(async () => { byTestId(view, "policy-row")[0].props.onClick(); });
  await settle();
  await click(view, "policy-drawer-edit");
  await settle();
  assert.equal(byTestId(view, "builder-pane-check").length, 1, "an existing builder policy opens on Check & save");
  await settle();
  assert.equal(srv.calls.find((call) => call.url.endsWith("/test-bench/generate")).body.original_id, "prod-read-only");
  assert.equal(byTestId(view, "builder-name")[0]?.props.value, undefined);
  await click(view, "builder-step-basics");
  await change(view, "builder-name", "Renamed");
  await settle();
  assert.deepEqual([lastRender(srv).id, lastRender(srv).name], ["prod-read-only", "Renamed"], "an existing @id is kept when the name changes");
  await change(view, "builder-id", "prod-read-only-v2");
  await settle();
  await click(view, "builder-save");
  await settle();
  assert.equal(puts(srv)[0].url.endsWith("/policies/prod-read-only"), true, "the path names the policy being replaced");
  assert.equal(puts(srv)[0].body.model.id, "prod-read-only-v2", "the model carries the new @id (a rename)");
  assert.equal(puts(srv)[0].body.create, false);

  await act(async () => { byTestId(view, "policy-row")[1].props.onClick(); });
  await settle();
  await click(view, "policy-drawer-edit");
  await settle();
  assert.equal(byTestId(view, "stub-editor")[0].props.value, HAND_TEXT);
  await change(view, "stub-editor", HAND_TEXT.replace("forbid", "permit"));
  await click(view, "policy-cedar-save");
  await settle();
  assert.match(text(byTestId(view, "policy-cedar-problem")[0]), /refuses this policy/);
  assert.equal(puts(srv).length, 1, "a refused statement is never saved");
  await change(view, "stub-editor", HAND_TEXT.replace("contractors", "vendors"));
  await click(view, "policy-cedar-save");
  await settle();
  const cedarPut = puts(srv)[1];
  assert.equal(cedarPut.url.endsWith("/policies/contractors-jira"), true);
  assert.deepEqual(cedarPut.body, { cedar: HAND_TEXT.replace("contractors", "vendors"), create: false });
  assert.ok(srv.calls.some((call) => call.url.endsWith("/validate")), "validated before saving");

  await act(async () => { byTestId(view, "policy-row")[0].props.onClick(); });
  await settle();
  const duplicate = view.root.findAll((node) => node.type === "button" && text(node) === "Duplicate")[0];
  await press(duplicate);
  await settle();
  assert.equal(lastRender(srv).id, "prod-read-only-copy");
  await click(view, "builder-back");

  await act(async () => { byTestId(view, "policy-row")[0].props.onClick(); });
  await settle();
  await click(view, "policy-drawer-remove");
  assert.match(text(byTestId(view, "policy-drawer-confirm-remove")[0]), /stops blocking once the draft is published/);
  assert.equal(srv.calls.some((call) => call.method === "DELETE"), false, "the first click only asks");
  await click(view, "policy-drawer-remove");
  await settle();
  const removed = srv.calls.find((call) => call.method === "DELETE");
  assert.equal(removed.url.endsWith("/policies/prod-read-only"), true);
  assert.equal(removed.headers["If-Match"], "sha256:3");
});

test("Edit as Cedar… converts a builder policy into a hand-written one after a confirmation", async () => {
  const srv = builderServer();
  const view = await renderPage(srv);
  await click(view, "policy-new");
  await change(view, "builder-name", "Seat block");
  await click(view, "builder-step-what");
  await click(view, "builder-action-use_seat");
  await settle();
  await click(view, "builder-edit-as-cedar");
  assert.equal(byTestId(view, "policy-cedar-editor").length, 0, "asks first");
  await click(view, "builder-cedar-confirm");
  await settle();
  assert.equal(byTestId(view, "stub-editor")[0].props.value, '@id("seat-block")\nforbid (principal, action == Action::"use_seat", resource);');
});

test("a changed draft is a conflict: the builder stays open and says so; a draft in review is frozen", async () => {
  const srv = builderServer({ conflict: true });
  const view = await renderPage(srv);
  await click(view, "policy-new");
  await change(view, "builder-name", "Seat block");
  await click(view, "builder-step-what");
  await click(view, "builder-action-use_seat");
  await settle();
  await click(view, "builder-save");
  await settle();
  assert.match(text(byTestId(view, "builder-problem")[0]), /Someone else changed the draft/);
  assert.equal(byTestId(view, "policy-builder").length, 1);

  const frozen = await renderPage(builderServer({ state: "in_review" }));
  assert.equal(byTestId(frozen, "policy-new")[0].props.disabled, true);
  await act(async () => { byTestId(frozen, "policy-row")[0].props.onClick(); });
  await settle();
  assert.equal(byTestId(frozen, "policy-drawer-edit")[0].props.disabled, true);
});

test("an empty instance offers three templates and saves into version 0 (the empty set)", async () => {
  const srv = builderServer({ state: "none", items: [] });
  const view = await renderPage(srv);
  const empty = byTestId(view, "policy-empty")[0];
  assert.equal(empty.findAll((node) => node.props["data-testid"] === "policy-template").length, 3);
  assert.equal(empty.findAll((node) => node.type === "p")[0].children.join(""), "No custom policies yet. The generated baseline keeps applying; add a policy to block more.",
    "one sentence; the actions are buttons below it, not inline");
  assert.equal(byTestId(view, "policy-empty-new")[0].props.disabled, false);
  await click(view, "policy-empty-new");
  await settle();
  assert.equal(byTestId(view, "policy-builder").length, 1, "the empty state's + New policy opens the builder");
  await click(view, "builder-back");
  await settle();
  await click(view, "policy-template-use-block-destructive-commands");
  await settle();
  assert.match(text(byTestId(view, "builder-target")[0]), /Creates a new draft/);
  await click(view, "builder-save");
  await settle();
  assert.equal(puts(srv)[0].url, "/api/v1/admin/policy-engine/policy-sets/0/policies/block-destructive-commands");
  assert.equal(puts(srv)[0].headers["If-Match"], "sha256:empty");
});

// ---- impact examples (G12) and lifecycle helpers ---------------------------------------------------------------

test("model: line diff, review and impact parsing, a test case from an example", () => {
  assert.deepEqual(lineDiff("a\nb\nc\n", "a\nc\nd\n"), [
    { kind: "same", text: "a" }, { kind: "removed", text: "b" }, { kind: "same", text: "c" }, { kind: "added", text: "d" }]);
  assert.deepEqual(lineDiff("", "x"), [{ kind: "added", text: "x" }]);
  assert.equal(lineDiff("a\n".repeat(3000), "b\n".repeat(3000)), null, "too large to diff in the browser");
  assert.equal(readReview({ review: null }), null);
  assert.equal(readReview({ review: { viewer: { can_approve: true }, approver_candidates: [{ id: "u" }] } }).candidates[0].name, "u");
  const impact = readImpact(IMPACT("p"));
  assert.equal(impact.examples.length, 4);
  assert.equal(impact.cases.failed, 1);
  assert.deepEqual(exampleCase(impact.examples[0], "Prod"), { name: "Prod: add_jira_comment is blocked", expected: "deny", request: impact.examples[0].request });
  assert.equal(exampleCase(impact.examples[3], "Prod").expected, "allow");
});

test("check step: examples answered against the draft with this policy; unexpected answers marked; saved as test cases", async () => {
  const srv = builderServer();
  const view = await renderPage(srv);
  await click(view, "policy-new");
  await change(view, "builder-name", "Jira read-only");
  await click(view, "builder-step-what");
  await click(view, "builder-action-write_connector");
  await settle();
  await click(view, "builder-step-check");
  await settle();
  const asked = srv.calls.find((call) => call.url.endsWith("/test-bench/generate"));
  assert.equal(asked.body.model.id, "jira-read-only");
  assert.equal(asked.body.original_id, null);
  const rows = byTestId(view, "policy-impact-example").map(text);
  assert.match(rows[0], /^Blockedadd_jira_comment is blocked · by jira-read-only/);
  assert.match(rows[1], /not as intended: this policy does not block it/);
  assert.match(rows[1], /· by Platform: tool permit, Claims · Workspace rule: kubectl requires context/, "readable labels, not raw ids");
  assert.doesNotMatch(rows[1], /platform:|workspace:ws-1/);
  const refs = byTestId(view, "policy-impact-example")[1].findAll((node) => node.props["data-testid"] === "policy-ref");
  assert.deepEqual(refs.map((node) => node.props.title), ["platform:tool-permit", "workspace:ws-1:tool-rule:kubectl-requires-context"], "raw id on hover");
  assert.match(rows[2], /^Error/);
  assert.match(rows[3], /— control/);
  assert.equal(byTestId(view, "policy-impact-unexpected").length, 2);
  assert.match(text(byTestId(view, "policy-impact-note")[0]), /Nobody matches the who-part/);
  assert.match(text(byTestId(view, "policy-tests-report")[0]), /1 of 1 saved test cases fail/);
  assert.equal(text(byTestId(view, "policy-tests-failure")[0]), "old case: expected allow, got deny (by jira-read-only, Platform: tool permit)");
  assert.equal(byTestId(view, "policy-impact-save")[2].props.disabled, true, "an error is not a test case");
  await click(view, "policy-impact-save", 0);
  await click(view, "policy-impact-save-all");
  const saved = srv.calls.filter((call) => call.url.endsWith("/tests") && call.method === "POST");
  assert.equal(saved.length, 4, "one, then the three answered examples");
  assert.deepEqual(saved[0].body, { name: "Jira read-only: add_jira_comment is blocked", expected: "deny", request: IMPACT("x").examples[0].request });
  assert.equal(saved[2].body.expected, "deny", "the intent, even though the policy does not block it yet");
  assert.equal(saved[3].body.expected, "allow");
  assert.match(text(byTestId(view, "policy-impact-message")[0]), /3 examples saved as test cases/);
});

test("drawer: a builder policy asks for its examples on demand, as itself", async () => {
  const srv = builderServer();
  const view = await renderPage(srv);
  await act(async () => { byTestId(view, "policy-row")[0].props.onClick(); });
  await settle();
  assert.equal(srv.calls.some((call) => call.url.endsWith("/test-bench/generate")), false, "not before asked");
  await click(view, "policy-impact-run");
  await settle();
  assert.equal(srv.calls.find((call) => call.url.endsWith("/test-bench/generate")).body.original_id, "prod-read-only");
  assert.equal(byTestId(view, "policy-impact-example").length, 4);
  await act(async () => { byTestId(view, "policy-row")[1].props.onClick(); });
  await settle();
  assert.equal(byTestId(view, "policy-impact").length, 0, "hand-written policies have no model to derive examples from");
});

test("draft shadow (G8): the Check step shows real traffic for a saved draft policy, and how to get it for a new one", async () => {
  assert.equal(readDraftImpact({ nope: 1 }), null);
  const parsed = readDraftImpact({ version: 3, total: 3, policies: { p: { count: 3, actions: { a: 1, b: 2 }, principals: 2 } } });
  assert.equal(actionBreakdown(parsed.policies.p), "2 × b, 1 × a");
  const srv = builderServer();
  const view = await renderPage(srv);
  await act(async () => { byTestId(view, "policy-row")[0].props.onClick(); });
  await settle();
  await click(view, "policy-drawer-edit");
  await settle();
  assert.match(text(byTestId(view, "draft-traffic")[0]), /would have blocked 4 requests \(4 × write_connector\) by 1 user\./);
  await click(view, "builder-back");
  await click(view, "policy-new");
  await change(view, "builder-name", "Seat block");
  await click(view, "builder-step-what");
  await click(view, "builder-action-use_seat");
  await settle();
  await click(view, "builder-step-check");
  await settle();
  assert.match(text(byTestId(view, "draft-traffic-pending")[0]), /Save it into the draft/);
});
