// Admin › Connections › Overview: "Spaces / Projects this connection serves" (bound_scopes) and what applies while a
// connection binds none (each Workspace's allowed list, else the global one). Backend rules: services/connections/
// writes.py (at most 100 keys, binding case, "keeps at least one key") and named_connections/resolver.py.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bindsFirstKeys,
  boundKeysProblem,
  boundScopesErrorText,
  firstBindingText,
  keysLeftOut,
  parseBoundKeys,
  readWorkspaceLimits,
  unboundTodayText,
} from "../../src/admin/components/connections/boundScopes.ts";
import { changesOf, draftOf } from "../../src/admin/components/connections/connectionDraft.ts";
import { readConnectionTypes } from "../../src/admin/components/connections/connectionTypes.ts";
import { readConnectionDetail } from "../../src/admin/components/connections/connectionsModel.ts";

const [confluence, jira, http] = readConnectionTypes([
  { type: "confluence", label: "Confluence", binding: { label: "space", plural: "Spaces", pattern: "~?[A-Za-z0-9_]{1,64}", case: "upper",
    example: "SPACE1, SPACE2", allowlist_field: "confluence_allowed_spaces", serves_unlisted: false } },
  { type: "jira", label: "Jira", binding: { label: "project", plural: "Projects", pattern: "[A-Za-z][A-Za-z0-9_]{0,63}", case: "upper",
    example: "PROJ1", allowlist_field: "jira_allowed_projects", serves_unlisted: true } },
  { type: "http", label: "HTTP" },
]);
const spaces = confluence.binding;

test("the catalog's binding becomes the editor's names and empty meaning; a type without one gets no editor", () => {
  assert.deepEqual([spaces.plural, spaces.allowlistField, spaces.servesUnlisted, spaces.upper], ["Spaces", "confluence_allowed_spaces", false, true]);
  assert.equal(jira.binding.servesUnlisted, true);
  assert.equal(http.binding, null);
});

test("keys are read as the server keeps them: binding case, any separator, no duplicates", () => {
  assert.deepEqual(parseBoundKeys(" shop, Docs;\nshop  ops ", spaces), ["SHOP", "DOCS", "OPS"]);
  assert.deepEqual(parseBoundKeys("", spaces), []);
});

test("a key the server would refuse is named before saving; more than 100 keys too", () => {
  assert.equal(boundKeysProblem(["SHOP", "~ALEX"], spaces), "");
  assert.match(boundKeysProblem(["SHOP", "DO-CS"], spaces), /"DO-CS" is not a space key/);
  assert.match(boundKeysProblem(Array.from({ length: 101 }, (_, i) => `S${i}`), spaces), /Up to 100 spaces; remove 1/);
});

test("the PUT carries bound_scopes only when the keys changed, as the whole list, and only for a type that binds keys", () => {
  const detail = readConnectionDetail({ id: "c1", type: "confluence", name: "Wiki", bound_scopes: ["SHOP"], access: { fields: {} } });
  assert.deepEqual(detail.boundScopes, ["SHOP"]);
  const before = draftOf(detail);
  assert.deepEqual(changesOf(before, { ...before, boundScopes: "shop" }, null, [], spaces), {});
  assert.deepEqual(changesOf(before, { ...before, boundScopes: "shop, docs" }, null, [], spaces), { bound_scopes: ["SHOP", "DOCS"] });
  assert.deepEqual(changesOf(before, { ...before, boundScopes: "" }, null, [], spaces), { bound_scopes: [] });
  assert.deepEqual(changesOf(before, { ...before, boundScopes: "docs" }, null, [], null), {});
});

test("the server's refusal at bound_scopes reads as words, including 'keeps at least one key'", () => {
  assert.match(boundScopesErrorText("This connection serves agent tools today and keeps at least one key.", spaces),
    /keeps at least one space\. Add one before removing the last/);
  assert.equal(boundScopesErrorText("bound_scopes must be a list of at most 100 keys.", spaces), "Up to 100 spaces.");
});

test("one batch read gives each Workspace's allowed spaces, rule objects included; none of its own = global; left-out ones stay out", () => {
  const shop = { id: "a", name: "Shop" }, ops = { id: "b", name: "Ops" }, hidden = { id: "c", name: "Someone's private" };
  const answer = { connector_name: "confluence", limit_fields: ["confluence_allowed_spaces"],
    inherited_limits: { confluence_allowed_spaces: ["OPS"] },
    workspaces: [{ project_id: "a", project_limits: { confluence_allowed_spaces: [{ space_key: "SHOP", enabled: true }, "DOCS"] } },
      { project_id: "b", project_limits: {} }] };
  assert.deepEqual(readWorkspaceLimits(answer, "confluence_allowed_spaces", [shop, ops, hidden]),
    { workspaces: [{ workspace: shop, own: ["SHOP", "DOCS"] }, { workspace: ops, own: null }], global: ["OPS"] });
  assert.equal(readWorkspaceLimits({ detail: "Unknown connector" }, "confluence_allowed_spaces", [shop]), null);
});

test("'Today, unbound' names each Workspace's list and the global one, empty worded per type", () => {
  const today = { workspaces: [{ workspace: { id: "a", name: "Shop" }, own: ["SHOP", "DOCS"] }, { workspace: { id: "b", name: "Ops" }, own: null }], global: [] };
  assert.equal(unboundTodayText(today, spaces), "Today, unbound: Shop → SHOP, DOCS; Ops → global list; global → no space (empty)");
  assert.match(unboundTodayText(today, jira.binding), /global → every project \(empty\)$/);
});

test("binding the first keys is confirmed and names the spaces other Workspaces would no longer read through it", () => {
  assert.equal(bindsFirstKeys([], ["SHOP"]), true);
  assert.equal(bindsFirstKeys(["SHOP"], ["SHOP", "DOCS"]), false);
  assert.equal(bindsFirstKeys([], []), false);
  const today = { workspaces: [{ workspace: { id: "a", name: "Shop" }, own: ["SHOP", "DOCS"] }, { workspace: { id: "b", name: "Ops" }, own: null }], global: ["OPS"] };
  const leftOut = keysLeftOut(today, ["SHOP"]);
  assert.deepEqual(leftOut, ["DOCS", "OPS"]);
  const text = firstBindingText(spaces, ["SHOP"], leftOut).join(" ");
  assert.match(text, /^Binding keys changes which runs use this connection\./);
  assert.match(text, /keep their allowed spaces only if their keys are bound too/);
  assert.match(text, /No longer read through this connection: DOCS, OPS\./);
});

test("removing the last keys is confirmed too and names the keys whose runs move away", async () => {
  const { unbindsAll, unbindText } = await import("../../src/admin/components/connections/boundScopes.ts");
  assert.equal(unbindsAll(["CHEF"], []), true);
  assert.equal(unbindsAll(["CHEF", "DOCS"], ["CHEF"]), false);
  assert.match(unbindText(spaces, ["CHEF"]).join(" "), /^Runs for CHEF no longer use this connection/);
});
