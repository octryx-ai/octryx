import assert from "node:assert/strict";
import { test } from "node:test";
import { KIND_LABEL } from "../../src/admin/components/workspaceKnowledge/connectorDisplay.ts";
import { configOf } from "../../src/admin/components/workspaceKnowledge/connectorConfig.ts";
import { CONNECTOR_KINDS, initialForm, pinnable, resetScope, validate } from "../../src/admin/components/workspaceKnowledge/connectorFormModel.ts";
import { scopeHint } from "../../src/admin/components/workspaceKnowledge/connectorScopeText.ts";

function form(patch = {}) {
  return { ...initialForm(null), ...resetScope("kubernetes"), key: "demo-inventory", cluster: "nonprod", ...patch };
}

test("a kubernetes connector is offered, pinnable and explained", () => {
  assert.ok(CONNECTOR_KINDS.includes("kubernetes"));
  assert.equal(KIND_LABEL.kubernetes, "Kubernetes inventory");
  assert.equal(pinnable("kubernetes"), true);
  assert.match(scopeHint("kubernetes"), /read-only/);
});

test("a kubernetes connector sends its cluster and namespaces only", () => {
  const checked = validate(form({ namespaces: "test, test ,prod", connectionId: "conn-1" }));
  assert.ok("config" in checked);
  const { config } = checked;
  assert.equal(config.kind, "kubernetes");
  assert.equal(config.cluster, "nonprod");
  assert.deepEqual(config.namespaces, ["test", "prod"]);
  assert.equal(config.connection_id, "conn-1");
  for (const field of ["spaces", "project_keys", "tables", "repository_url", "releases"]) assert.equal(config[field], undefined);
});

test("cluster and namespace names follow the server's rules", () => {
  assert.match(validate(form({ cluster: "" })).problem, /cluster name/);
  assert.match(validate(form({ cluster: "has space" })).problem, /cluster name/);
  assert.ok("config" in validate(form({ cluster: "arn:aws:eks:eu-central-1:1:cluster/shop" })));
  assert.match(validate(form({ namespaces: "Risk_Test" })).problem, /namespace name/);
  const many = Array.from({ length: 51 }, (_, index) => `ns-${index}`).join(",");
  assert.match(validate(form({ namespaces: many })).problem, /at most 50/);
});

test("a stored kubernetes connector loads back and its pause toggle keeps the scope and pin", () => {
  const connector = {
    connector_key: "demo-inventory", kind: "kubernetes",
    scope: { cluster: "nonprod", namespaces: ["test"], connection_id: "conn-1" },
    products: [], version: null, max_items_per_run: 100, state: "active",
    schedule: { enabled: true, interval_minutes: 360, next_run_at: null },
  };
  const loaded = initialForm(connector);
  assert.equal(loaded.kind, "kubernetes");
  assert.equal(loaded.cluster, "nonprod");
  assert.equal(loaded.namespaces, "test");
  const paused = configOf(connector, "paused");
  assert.equal(paused.state, "paused");
  assert.equal(paused.cluster, "nonprod");
  assert.deepEqual(paused.namespaces, ["test"]);
  assert.equal(paused.connection_id, "conn-1");
  assert.equal(resetScope("jira").cluster, "");
});
