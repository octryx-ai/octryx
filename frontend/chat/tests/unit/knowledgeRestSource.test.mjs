import assert from "node:assert/strict";
import { test } from "node:test";
import { configOf } from "../../src/admin/components/workspaceKnowledge/connectorConfig.ts";
import { connectorRequest } from "../../src/admin/components/workspaceKnowledge/connectorsApi.ts";
import { initialForm, resetScope, validate } from "../../src/admin/components/workspaceKnowledge/connectorFormModel.ts";
import { sourceState } from "../../src/admin/components/workspaceKnowledge/sources/sourceState.ts";
import { WORKSPACE_ADMIN_ONLY, livePathProblems, restKnowledgeBody, restKnowledgeProblems, visibilityRule } from "../../src/admin/components/workspaceKnowledge/rest/restSourceRules.ts";
import { aclNotice, restSampleView, restStatus } from "../../src/admin/components/workspaceKnowledge/rest/restSourceSample.ts";
import { emptyRestKnowledgeForm, restKnowledgeFormOf, withContentFrom } from "../../src/admin/components/workspaceKnowledge/rest/restSourceForm.ts";
import { restRefusalOf } from "../../src/admin/components/workspaceKnowledge/rest/restSourceRefusals.ts";

// The operations the Workspace discovery returns for the desk API (intake/fields): a list and a detail read.
const LIST = { op_key: "list_articles", name: "list_articles", method: "GET", path: "/articles", roles: ["admin", "operator"], scoped_roles: ["admin"], role_required: true };
const DETAIL = { op_key: "get_article", name: "get_article", method: "GET", path: "/articles/{id}", roles: ["admin", "operator"], scoped_roles: [], role_required: false };
const TWO_PARAMS = { op_key: "get_rev", name: "get_rev", method: "GET", path: "/articles/{id}/revisions/{rev}", roles: ["operator"], scoped_roles: [], role_required: false };
const OPERATIONS = [LIST, DETAIL, TWO_PARAMS];

function filled(patch = {}) {
  return {
    ...emptyRestKnowledgeForm(), definition: "desk", operation: "list_articles", role: "operator",
    mapping: { title: "title", id: "id", url: "link", updated_at: "updated", version: "" }, ...patch,
  };
}

test("a new REST source is restricted by grant and reads the listed record as JSON", () => {
  const form = { ...initialForm(null), ...resetScope("custom_rest"), key: "desk-articles" };
  assert.equal(form.rest.visibility, "restricted");
  assert.equal(form.rest.contentFrom, "record");
  assert.equal(form.rest.mediaType, "application/json");
  const checked = validate({ ...form, rest: filled() });
  assert.ok("config" in checked, JSON.stringify(checked));
  assert.equal(checked.config.kind, "custom_rest");
  assert.equal(checked.config.scope.visibility, "restricted");
  assert.deepEqual(checked.config.mapping, { title: "title", id: "id", url: "link", updated_at: "updated" });
  // No field of another kind travels with it (the server refuses scope/mapping next to built-in fields and vice versa).
  for (const key of ["spaces", "project_keys", "connection_id", "repository_url"]) assert.equal(key in checked.config, false, key);
});

test("only a platform admin may choose 'everyone in the Workspace'; the server's 403 reads the same at the field", () => {
  assert.deepEqual(visibilityRule(true), { workspaceAllowed: true, hint: null });
  assert.equal(visibilityRule(false).workspaceAllowed, false);
  assert.equal(restKnowledgeProblems(filled({ visibility: "workspace" }), OPERATIONS, false)["scope.visibility"], WORKSPACE_ADMIN_ONLY);
  assert.equal(restKnowledgeProblems(filled({ visibility: "workspace" }), OPERATIONS, true)["scope.visibility"], undefined);
  const refusal = restRefusalOf({ status: 403, reason: "rest_source_visibility_admin_only", field: "scope.visibility" });
  assert.deepEqual(refusal, { field: "scope.visibility", text: WORKSPACE_ADMIN_ONLY });
});

test("the 403 carries `code`, not `reason`: the client still keeps it as the refusal's reason", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: { code: "rest_source_visibility_admin_only", field: "scope.visibility", message: "x" } }),
    { status: 403, headers: { "Content-Type": "application/json" } });
  try {
    await assert.rejects(connectorRequest("/x", { method: "PUT", body: "{}" }), (error) => {
      assert.equal(error.reason, "rest_source_visibility_admin_only");
      assert.equal(error.status, 403);
      assert.equal(restRefusalOf(error).field, "scope.visibility");
      assert.doesNotMatch(error.message, /rest source visibility admin only/);
      return true;
    });
  } finally {
    globalThis.fetch = original;
  }
});

test("the content variants build the body the server validates", () => {
  const record = restKnowledgeBody(filled({ contentPath: "ignored" }));
  assert.equal(record.scope.media_type, "application/json");
  assert.equal("detail_operation" in record.scope, false);
  assert.equal("content" in record.mapping, false);

  const detail = restKnowledgeBody(withContentFrom(filled(), "detail"));
  assert.equal("detail_operation" in detail.scope, true);
  const detailForm = { ...withContentFrom(filled(), "detail"), detailOperation: "get_article", detailParam: "id", contentPath: "body" };
  const body = restKnowledgeBody(detailForm);
  assert.equal(body.scope.detail_operation, "get_article");
  assert.equal(body.scope.detail_param, "id");
  assert.equal(body.mapping.content, "body");
  assert.equal(body.scope.media_type, "application/json");

  const field = withContentFrom(filled(), "field");
  assert.equal(field.mediaType, "text/markdown");
  assert.equal(restKnowledgeProblems(field, OPERATIONS, false)["mapping.content"], "Name the field that holds the text.");
  assert.equal(restKnowledgeBody({ ...field, contentPath: "body" }).mapping.content, "body");

  // Leaving the detail variant drops the detail operation, so it is never sent with the wrong variant.
  const back = withContentFrom(detailForm, "field");
  assert.equal(back.detailOperation, "");
  assert.equal("detail_operation" in restKnowledgeBody({ ...back, contentPath: "body" }).scope, false);
});

test("a detail operation needs one decidable id argument", () => {
  const detail = withContentFrom(filled(), "detail");
  assert.equal(restKnowledgeProblems(detail, OPERATIONS, false)["scope.detail_operation"], "Pick the read operation that returns one record.");
  assert.equal(restKnowledgeProblems({ ...detail, detailOperation: "get_article" }, OPERATIONS, false)["scope.detail_param"], undefined);
  assert.ok(restKnowledgeProblems({ ...detail, detailOperation: "get_rev" }, OPERATIONS, false)["scope.detail_param"]);
  assert.equal(restKnowledgeProblems({ ...detail, detailOperation: "get_rev", detailParam: "id" }, OPERATIONS, false)["scope.detail_param"], undefined);
});

test("dot paths, required fields and the version-or-updated rule", () => {
  const problems = restKnowledgeProblems(filled({ mapping: { title: "fields..name", id: "", url: "a b", updated_at: "", version: "" } }), OPERATIONS, false);
  assert.match(problems["mapping.title"], /empty step/);
  assert.match(problems["mapping.url"], /no spaces/);
  assert.match(problems["mapping.id"], /Map the id/);
  assert.match(problems["mapping.updated_at"], /Updated or Version/);
  assert.equal(restKnowledgeProblems(filled({ mapping: { title: "t", id: "sys.id", url: "", updated_at: "", version: "rev" } }), OPERATIONS, false)["mapping.updated_at"], undefined);
  // While typing only a malformed path shows, never "required" before a save was tried.
  assert.deepEqual(Object.keys(livePathProblems(filled({ mapping: { title: "", id: "x y", url: "", updated_at: "", version: "" } }))), ["mapping.id"]);
  // A scoped list operation needs the role; the server's refusal of a path lands at its field.
  assert.match(restKnowledgeProblems(filled({ role: "" }), OPERATIONS, false)["scope.role"], /Pick the role/);
  assert.deepEqual(restRefusalOf({ status: 422, reason: "custom_rest_invalid_path", field: "mapping.url" }), { field: "mapping.url", text: "Link: use a dot path, like fields.summary." });
  assert.equal(restRefusalOf({ status: 409, reason: "custom_rest_role_not_granted" }).field, "scope.role");
});

test("a stored source reopens in the variant it was saved with, and saves back the same body", () => {
  const stored = { ...restKnowledgeBody({ ...withContentFrom(filled(), "detail"), detailOperation: "get_article", detailParam: "id", contentPath: "body" }).scope,
    mapping: { title: "title", id: "id", updated_at: "updated", content: "body" } };
  const form = restKnowledgeFormOf(stored);
  assert.equal(form.contentFrom, "detail");
  assert.equal(form.visibility, "restricted");
  const again = restKnowledgeBody(form);
  assert.equal(again.scope.detail_operation, "get_article");
  assert.equal(again.mapping.content, "body");
  assert.equal(restKnowledgeFormOf({ ...stored, detail_operation: null, media_type: "text/markdown" }).contentFrom, "field");
});

test("pause and resume send the stored scope and mapping unchanged", () => {
  const scope = { definition: "desk", operation: "list_articles", role: "operator", visibility: "restricted", mapping: { id: "id", title: "title", version: "rev" } };
  const config = configOf({ connector_key: "desk", kind: "custom_rest", scope, products: [], version: null, max_items_per_run: 50, state: "active", cursor: {}, running: false, last_run: null }, "paused");
  assert.equal(config.kind, "custom_rest");
  assert.equal(config.state, "paused");
  assert.deepEqual(config.mapping, { id: "id", title: "title", version: "rev" });
  assert.equal("mapping" in config.scope, false);
  assert.equal(config.scope.role, "operator");
});

test("the dry run shows a restricted item as hidden with why, and counts skipped and dropped records", () => {
  const view = restSampleView({
    items: [
      { external_id: "KB-1", title: "Reset a label printer", source_url: "https://desk.example.test/kb/KB-1", source_changed_at: "2026-11-12T09:30:00+00:00",
        acl: { audience: "restricted", restriction: "octryx_grant", principals: ["role:admin", "role:operator"] },
        excerpt: "Hold the feed key. Token [redacted] stays out." },
      { external_id: "KB-3", hidden: true, acl: { audience: "restricted", restriction: "octryx_grant", principals: ["role:operator"] } },
    ],
    listed: 3, skipped: [{ record: "record-3", reason: "record_without_id" }], last_page: true,
    listing: { role: "operator", pages: 1, dropped_out_of_scope: 2 },
    first_item_content: { external_id: "KB-1", media_type: "text/markdown", bytes: 900, text: `## Reset\n\n${"word ".repeat(100)}` },
    first_item_members: { admitted: 2, unmapped: 1 },
    acl: { visibility: "restricted", acl_enforced: false, restricted_items_withheld: true, note: "…" },
  });
  assert.equal(view.listed, 3);
  assert.equal(view.hidden, 1);
  const hidden = view.rows.find((row) => row.hidden);
  assert.equal(hidden.title, "");
  assert.match(hidden.who, /^Hidden from you: only the role operator may read it/);
  assert.equal(view.rows[0].who, "People with the roles admin, operator");
  assert.deepEqual(view.skippedReasons, ["1 without an id"]);
  assert.equal(view.dropped, 2);
  assert.equal(view.role, "operator");
  assert.deepEqual(view.members, { admitted: 2, unmapped: 1 });
  assert.equal(view.acl.restricted_items_withheld, true);
});

test("the status says when restricted items are held back, what an admin switches on, and the next sync", () => {
  const withheld = { visibility: "restricted", acl_enforced: false, restricted_items_withheld: true, note: "server note" };
  const notice = aclNotice(withheld);
  assert.doesNotMatch(JSON.stringify(notice), /knowledge_source_acl/);
  assert.match(notice.text, /does not enforce source permissions/);
  assert.equal(aclNotice({ ...withheld, acl_enforced: true, restricted_items_withheld: false }), null);
  assert.equal(aclNotice({ ...withheld, visibility: "workspace", restricted_items_withheld: false }), null);

  const connector = {
    connector_key: "desk-articles", kind: "custom_rest", products: [], version: null, max_items_per_run: 20, state: "active", running: false,
    scope: { definition: "desk", operation: "list_articles", role: "operator", detail_operation: "get_article", visibility: "restricted", mapping: {} },
    cursor: { pass_number: 1, token: null, pass_started_at: null, last_completed_at: "2026-11-15T10:00:00Z", completed_passes: 1 },
    schedule: { enabled: true, interval_minutes: 60, next_run_at: "2026-11-15T11:00:00Z" },
    last_run: { id: "r", state: "completed", reason: null, report: { listed: 3, created: 0, skipped: 3, failed: 1 }, started_at: "2026-11-15T10:00:00Z", finished_at: "2026-11-15T10:00:05Z" },
    acl: withheld,
  };
  const status = restStatus(connector);
  assert.equal(status.readAs, "operator");
  assert.equal(status.reads, "desk · list_articles, content from get_article");
  assert.equal(status.nextSync, "2026-11-15T11:00:00Z");
  assert.equal(status.errors, "1 item failed in the last sync.");
  assert.ok(status.notice);
  assert.equal(restStatus({ ...connector, last_run: { ...connector.last_run, state: "failed", reason: "custom_rest_role_not_granted" } }).errors,
    "The last sync failed: this role has no grant on the operation in this Workspace. Pick a granted role.");
  assert.equal(restStatus({ ...connector, schedule: { enabled: false, interval_minutes: 60, next_run_at: null } }).nextSync, null);
  assert.equal(restStatus({ ...connector, last_run: { ...connector.last_run, report: { skipped: 4, skipped_reasons: { record_without_id: 1, restricted_acl: 3 } } } }).errors,
    "None. Skipped: 1 without an id.");
  // The sources list says it too, as the source's state.
  const state = sourceState({ ...connector, last_run: { ...connector.last_run, report: { listed: 3, skipped: 3 } } }, false, true, Date.parse("2026-11-15T10:30:00Z"));
  assert.equal(state.word, "Needs attention");
  assert.match(state.reason, /held back/);
});
