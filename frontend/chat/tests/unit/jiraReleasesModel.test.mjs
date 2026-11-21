import assert from "node:assert/strict";
import { test } from "node:test";
import { configOf } from "../../src/admin/components/workspaceKnowledge/connectorConfig.ts";
import {
  blockFromDraft,
  checkDraft,
  draftFromBlock,
  errorsFor,
  isDirty,
  releasesPayload,
  tagProblem,
} from "../../src/admin/components/workspaceKnowledge/jiraReleasesModel.ts";

const BLOCK = {
  products: { OPS: "acme-orders" },
  version_name_prefixes: ["Release "],
  sections: [{ title: "Features", issue_types: ["Story"], labels: [] }],
  blocker_priorities: ["Blocker"],
};

const CONNECTOR = {
  connector_key: "ops",
  kind: "jira",
  scope: { project_keys: ["OPS", "PLAT"], jql: null, releases: BLOCK },
  products: ["acme-orders"],
  version: null,
  max_items_per_run: 50,
  state: "paused",
  schedule: { enabled: true, interval_minutes: 60, next_run_at: null },
  running: false,
  last_run: null,
  cursor: { pass_number: 1, token: "secret-cursor", pass_started_at: null, last_completed_at: null, completed_passes: 0 },
};

test("the PUT body is the whole stored configuration with only the block replaced", () => {
  const draft = draftFromBlock(BLOCK);
  draft.blockerPriorities.push("Critical");
  const body = releasesPayload(CONNECTOR, draft);
  assert.deepEqual(body, {
    kind: "jira", project_keys: ["OPS", "PLAT"], jql: null, products: ["acme-orders"], version: null,
    max_items_per_run: 50, state: "paused", schedule_enabled: true, schedule_interval_minutes: 60,
    releases: { ...BLOCK, blocker_priorities: ["Blocker", "Critical"] },
  });
  // Switching off sends null; nothing outside the allowlist (cursor, last run) is ever sent back.
  assert.equal(releasesPayload(CONNECTOR, { ...draft, enabled: false }).releases, null);
  assert.ok(!JSON.stringify(body).includes("secret-cursor"));
});

test("pausing or resuming a Jira connector keeps its releases block", () => {
  assert.deepEqual(configOf(CONNECTOR, "active").releases, BLOCK);
  assert.equal(configOf({ ...CONNECTOR, scope: { project_keys: ["OPS"] } }).releases, null);
});

test("a round trip is clean; prefixes keep their spaces, keys take the stored case", () => {
  assert.equal(isDirty(draftFromBlock(BLOCK), BLOCK), false);
  assert.equal(isDirty(draftFromBlock(null), undefined), false);
  const draft = draftFromBlock(BLOCK);
  draft.products.push({ id: 99, projectKey: " plat ", product: " Data-Platform " });
  assert.deepEqual(blockFromDraft(draft).products, { OPS: "acme-orders", PLAT: "data-platform" });
  assert.deepEqual(blockFromDraft(draft).version_name_prefixes, ["Release "]);
  assert.equal(isDirty(draft, BLOCK), true);
});

test("shape checks use the server's field paths; bounds and scope are left to the server", () => {
  const draft = draftFromBlock(BLOCK);
  draft.products.push({ id: 1, projectKey: "OPS", product: "other" }, { id: 2, projectKey: "FIN", product: "x" });
  draft.sections.push({ id: 3, title: " ", issueTypes: [], labels: [] });
  draft.prefixes.push("x".repeat(80));
  assert.deepEqual(checkDraft(draft), {
    "releases.products[1]": "client_duplicate",
    "releases.sections[1].title": "client_required",
    "releases.sections[1]": "release_section_without_match",
  });
  const server = { "releases.sections[0].labels[2]": "release_value_too_long", "releases.sections[10]": "x" };
  assert.deepEqual(errorsFor(server, "releases.sections[0].labels").map(([path]) => path), ["releases.sections[0].labels[2]"]);
  assert.deepEqual(errorsFor(server, "releases.sections[1]"), []);
});

test("tags refuse blanks and duplicates; prefixes are literal, other values case-insensitive", () => {
  assert.equal(tagProblem("releases.blocker_priorities", "  ", []), "client_required");
  assert.equal(tagProblem("releases.blocker_priorities", "blocker", ["Blocker"]), "client_duplicate");
  assert.equal(tagProblem("releases.version_name_prefixes", "Release", ["Release "]), null);
  assert.equal(tagProblem("releases.version_name_prefixes", "Release ", ["Release "]), "client_duplicate");
});
