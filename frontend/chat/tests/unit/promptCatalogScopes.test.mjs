import assert from "node:assert/strict";
import { test } from "node:test";
import { promptTextsHref, readPromptScopeFromSearch } from "../../src/admin/editorLinks.ts";
import {
  contextOf,
  describePromptRefusal,
  effectiveText,
  parseScopeKey,
  placeholderMeanings,
  scopeChoices,
  scopeKey,
  scopeNames,
  sourceLabel,
  subGroupsOf,
} from "../../src/admin/components/promptCatalog/promptCatalogModel.ts";
import { RegistryApiError } from "../../src/admin/components/governedRegistry/registryApi.ts";

function template(scope_type, scope_id, version, body) {
  return {
    id: `${scope_type}:${scope_id}`,
    key: "run.read_contract",
    scope_type,
    scope_id,
    scope_key: scope_id ? `${scope_type}:${scope_id}` : "global",
    versions: [
      { id: `${scope_id}-pub`, version, state: "published", body },
      { id: `${scope_id}-draft`, version: version + 1, state: "draft", body: "not yet" },
    ],
  };
}

const templates = [
  template("global", null, 2, "global text"),
  template("workflow", "epic-delivery", 1, "workflow text"),
  template("workspace", "ws-1", 3, "workspace text"),
];

test("a run gets the most specific published text: workspace over workflow over global", () => {
  const both = effectiveText(templates, "seed", { workflow: "epic-delivery", workspace: "ws-1" });
  assert.equal(both.body, "workspace text");
  assert.deepEqual(both.scope, { scope_type: "workspace", scope_id: "ws-1" });
  assert.equal(effectiveText(templates, "seed", contextOf({ scope_type: "workflow", scope_id: "epic-delivery" })).body, "workflow text");
  // A workflow without its own text falls back to the global one, never to another workflow's.
  const other = effectiveText(templates, "seed", { workflow: "spec-writing" });
  assert.equal(other.body, "global text");
  assert.deepEqual(other.scope, { scope_type: "global", scope_id: null });
});

test("drafts are never served: without any published text the shipped text is used", () => {
  const onlyDrafts = [{ ...templates[0], versions: [templates[0].versions[1]] }];
  assert.deepEqual(effectiveText(onlyDrafts, "seed", {}), { body: "seed", scope: null, version: null });
});

test("the source line names where the text comes from", () => {
  const names = new Map([["workspace:ws-1", "Payments"]]);
  assert.equal(sourceLabel({ scope_type: "workspace", scope_id: "ws-1" }, names), "the text from workspace Payments");
  assert.equal(sourceLabel({ scope_type: "workflow", scope_id: "epic-delivery" }, names), "the text from workflow epic-delivery");
  assert.equal(sourceLabel({ scope_type: "global", scope_id: null }, names), "the global text");
  assert.equal(sourceLabel(null, names), "the shipped text");
});

test("scope choices: only server-writable scopes are writable, visible texts stay readable, global always listed", () => {
  const choices = scopeChoices(
    [{ scope_type: "workspace", scope_id: "ws-1", label: "Payments" }],
    templates,
  );
  assert.deepEqual(
    choices.map((choice) => [scopeKey(choice), choice.label, choice.writable]),
    [
      ["global", "Global", false],
      ["workflow:epic-delivery", "epic-delivery", false],
      ["workspace:ws-1", "Payments", true],
    ],
  );
  assert.equal(scopeNames(choices).get("workspace:ws-1"), "Payments");
});

test("the workflow editor link round-trips its scope", () => {
  const href = promptTextsHref("workflow:epic-delivery");
  const scope = parseScopeKey(readPromptScopeFromSearch(href.slice(href.indexOf("?"))));
  assert.deepEqual(scope, { scope_type: "workflow", scope_id: "epic-delivery" });
  assert.equal(parseScopeKey("agent_definition:a"), null);
  assert.equal(parseScopeKey("workspace:"), null);
  assert.equal(parseScopeKey(""), null);
});

test("sub-groups follow the server's group_order; ungrouped keys go to Other, last", () => {
  const groups = subGroupsOf([
    { key: "a", group: "Evidence", group_order: 30 },
    { key: "b", group: null },
    { key: "c", group: "Continuation", group_order: 10 },
    { key: "d", group: "Evidence", group_order: 30 },
    { key: "e", group: "New group" },
  ]);
  assert.deepEqual(
    groups.map((group) => [group.label, group.items.map((item) => item.key)]),
    [
      ["Continuation", ["c"]],
      ["Evidence", ["a", "d"]],
      ["New group", ["e"]],
      ["Other", ["b"]],
    ],
  );
});

test("placeholder meanings come from the key spec; a missing one leaves the name alone", () => {
  assert.deepEqual(placeholderMeanings(["run_id", "phase"], { run_id: "The id of this run." }), [
    { name: "run_id", meaning: "The id of this run." },
    { name: "phase", meaning: null },
  ]);
});

test("a scope refusal says in plain words who may write there, never the code", () => {
  for (const [scope_type, words] of [["workspace", "owner or admin of this Workspace"], ["workflow", "workflow's creator"], ["global", "platform admin"]]) {
    const refusal = describePromptRefusal(new RegistryApiError(403, "prompt_scope_forbidden", { scope_type }, "forbidden"));
    assert.ok(refusal.text.includes(words), refusal.text);
    assert.ok(!refusal.text.includes("prompt_scope_forbidden"));
  }
  const missing = describePromptRefusal(new RegistryApiError(404, "prompt_workflow_not_found", {}, "x"));
  assert.match(missing.text, /No workflow with this key exists/);
});

test("the versions table names a scope by its workspace or workflow name, not its id", async () => {
  const { scopeLabel } = await import("../../src/admin/components/promptCatalog/promptCatalogModel.ts");
  const names = scopeNames(scopeChoices([{ scope_type: "workspace", scope_id: "ws-1", label: "Payments" }], []));
  assert.equal(scopeLabel({ scope_type: "workspace", scope_id: "ws-1" }, names), "Workspace · Payments");
});

test("the reviewer's approve and reject go to the approvals API of the version's approval", async () => {
  const { createPromptCatalogApi } = await import("../../src/admin/components/promptCatalog/promptCatalogApi.ts");
  const calls = [];
  const api = createPromptCatalogApi(async (url, init) => {
    calls.push([url, init?.method, JSON.parse(init?.body ?? "{}")]);
    return new Response("{}", { status: 200, headers: { "Content-Type": "application/json" } });
  });
  await api.approve("ap-1");
  await api.reject("ap-1", "too vague");
  assert.deepEqual(calls.map(([url, method]) => [url, method]), [
    ["/api/v1/approvals/ap-1/approve", "POST"],
    ["/api/v1/approvals/ap-1/reject", "POST"],
  ]);
  assert.equal(calls[1][2].reason, "too vague");
});
