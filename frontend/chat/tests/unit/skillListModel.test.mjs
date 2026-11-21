import assert from "node:assert/strict";
import { test } from "node:test";
import { countInCategory, cutText, filterRows, inCategory, isRetired, rowTags, EMPTY_FILTERS } from "../../src/admin/components/skillCatalog/skillListModel.ts";

const version = (n, state) => ({ version: n, state, digest: `sha256:${n}`, updated_at: null });
const row = (name, patch = {}) => ({
  id: name, name, kind: "skill", tags: [], description: "", category: null, published: version(1, "published"), open: null,
  available: { platform_chat: true, octryx_claude: false }, source: null, tracking_mode: null, update_available: false,
  upstream_status: null, uses: 0, workspaces: 0, ...patch,
});
const cat = (key) => ({ id: key, key, label: key, path: key.split(".") });
const rows = [
  row("terraform-style-guide", { category: cat("iac.terraform"), tags: ["terraform"], update_available: true, open: version(3, "draft"),
    available: { platform_chat: true, octryx_claude: true }, source: { id: "s", label: "hashicorp/agent-skills", trust: "official", kind: "git" } }),
  row("helm", { category: cat("kubernetes.helm"), tags: ["helm", "read-only"], description: "Scaffold Helm charts",
    source: { id: "m", label: "wshobson/agents", trust: "community", kind: "marketplace" } }),
  row("alert-diagnosis", { category: cat("diagnosis"), open: version(2, "in_review") }),
  row("old", { category: cat("iac"), published: null, source: { id: "u", label: "Uploaded files", trust: "community", kind: "upload" } }),
];
const pick = (filters) => filterRows(rows, { ...EMPTY_FILTERS, ...filters }).map((item) => item.name);

test("the category filter matches the key and every child key, never a prefix of another key", () => {
  assert.equal(inCategory(rows[0], "iac"), true);
  assert.equal(inCategory(rows[0], "iac.terraform"), true);
  assert.equal(inCategory(row("x", { category: cat("iac-legacy") }), "iac"), false);
  assert.equal(countInCategory(rows, "iac"), 2);
  assert.deepEqual(pick({ category: "kubernetes" }), ["helm"]);
});

test("status, surface, source, tag and text filters are explicit fields", () => {
  assert.deepEqual(pick({ status: "update" }), ["terraform-style-guide"]);
  assert.deepEqual(pick({ status: "draft" }), ["terraform-style-guide"]);
  assert.deepEqual(pick({ status: "in_review" }), ["alert-diagnosis"]);
  assert.deepEqual(pick({ status: "retired" }), ["old"]);
  assert.deepEqual(pick({ surface: "octryx_claude" }), ["terraform-style-guide"]);
  assert.deepEqual(pick({ source: "official" }), ["terraform-style-guide"]);
  assert.deepEqual(pick({ source: "marketplace" }), ["helm"]);
  assert.deepEqual(pick({ source: "git" }), ["terraform-style-guide"]);
  assert.deepEqual(pick({ source: "upload" }), ["old"]);
  assert.deepEqual(pick({ source: "custom" }), ["alert-diagnosis"]);
  assert.deepEqual(pick({ tag: "helm" }), ["helm"]);
  assert.deepEqual(pick({ query: "SCAFFOLD" }), ["helm"]);
  assert.deepEqual(pick({ query: "read-only" }), ["helm"]);
});

test("tags, retired rows and description cuts", () => {
  assert.deepEqual(rowTags(rows), ["helm", "read-only", "terraform"]);
  assert.equal(isRetired(rows[3]), true);
  assert.equal(isRetired(rows[2]), false);
  assert.equal(cutText("a".repeat(92)), "a".repeat(92));
  assert.equal(cutText("a".repeat(93)), `${"a".repeat(92)}…`);
});
