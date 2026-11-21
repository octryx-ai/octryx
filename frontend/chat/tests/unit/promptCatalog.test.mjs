import assert from "node:assert/strict";
import { test } from "node:test";
import { createPromptCatalogApi } from "../../src/admin/components/promptCatalog/promptCatalogApi.ts";
import {
  describePromptRefusal,
  diffLines,
  groupByArea,
  placeholderPreview,
  scopeLabel,
} from "../../src/admin/components/promptCatalog/promptCatalogModel.ts";

function item(key, area) {
  return { key, area, title: key, description: "", risk: "standard", placeholders: [], published: null, seed_digest: "", open_versions: 0, override_count: 0 };
}

function refusing(status, detail) {
  return async () => new Response(JSON.stringify({ detail }), { status, headers: { "Content-Type": "application/json" } });
}

test("keys are grouped by area, areas and keys sorted", () => {
  const groups = groupByArea([item("system.z", "system"), item("evidence.a", "evidence"), item("system.a", "system")]);
  assert.deepEqual(
    groups.map((group) => [group.area, group.items.map((row) => row.key)]),
    [
      ["evidence", ["evidence.a"]],
      ["system", ["system.a", "system.z"]],
    ],
  );
});

test("the placeholder preview flags names outside the closed set, like the server", () => {
  const preview = placeholderPreview('Mode {mode_name}, {user_email}, {mode_name} and JSON {"a": 1}.', ["mode_name"]);
  assert.deepEqual(preview, { used: ["mode_name", "user_email"], unknown: ["user_email"] });
});

test("unified diff lines are classified for +/- styling", () => {
  const lines = diffLines("--- a@seed\n+++ a@2\n@@ -1 +1 @@\n-old\n+new\n same\n");
  assert.deepEqual(
    lines.map((line) => line.kind),
    ["header", "header", "hunk", "removed", "added", "context"],
  );
  assert.deepEqual(diffLines(""), []);
});

test("scope labels name the Workspace when it is known", () => {
  const names = new Map([["w1", "Payments"]]);
  assert.equal(scopeLabel({ scope_type: "global", scope_id: null }, names), "Global");
  assert.equal(scopeLabel({ scope_type: "workspace", scope_id: "w1" }, names), "Workspace · Payments");
});

test("a placeholder refusal keeps its code and names the unknown placeholders", async () => {
  const api = createPromptCatalogApi(
    refusing(422, { code: "prompt_template_unavailable", key: "system.base.full", reason: "placeholder_unknown", names: ["user_email"] }),
  );
  const error = await api.createDraft("system.base.full", { scope_type: "global", scope_id: null, body: "{user_email}", change_note: "" }).catch((caught) => caught);
  const refusal = describePromptRefusal(error);
  assert.equal(refusal.code, "prompt_template_unavailable");
  assert.deepEqual(refusal.names, ["user_email"]);
  assert.match(refusal.text, /does not declare: user_email\./);
});

test("a governance refusal carries the approval gate status", async () => {
  const api = createPromptCatalogApi(
    refusing(409, { code: "governance_approval_required", approval_gate: { status: "pending", approval_id: "ap1" } }),
  );
  const refusal = describePromptRefusal(await api.publish("v1", "ap1").catch((caught) => caught));
  assert.equal(refusal.code, "governance_approval_required");
  assert.match(refusal.detail ?? "", /^pending:/);
});
