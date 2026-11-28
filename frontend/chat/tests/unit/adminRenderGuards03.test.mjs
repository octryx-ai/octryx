// Render guards for admin panels, hooks and actions split into smaller functions: a user's API keys, the role actions,
// the PR review bot cards, the answer feedback panel, the model catalog sync drawer, the knowledge changes panel, the
// documentation target card and the providers list render (or act) the same after being split up.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { load } from "./adminPartsLoader.mjs";
import { act, byTestId, server, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, noop, plain, testIds } from "./adminGuardRenderers.mjs";

test("a user's API keys load, create with scopes and expiry, revoke after a confirm, and reset on close", async () => {
  const calls = [];
  const readJson = async (url, init = {}) => {
    calls.push([init.method ?? "GET", url, init.body ? JSON.parse(init.body) : null]);
    if (init.method === "POST") return { id: "k2", name: "ci", api_key: "secret-1" };
    if (init.method === "DELETE") return { id: "k1", name: "old", revoked: true };
    return [{ id: "k1", name: "old" }];
  };
  let confirmAnswer = false;
  const { useAdminUserApiKeys } = load("admin/components/usersTab/useAdminUserApiKeys.ts", { confirm: () => confirmAnswer });
  let state;
  const Probe = () => { state = useAdminUserApiKeys(readJson); return null; };
  await createAsync(createElement(Probe));
  assert.deepEqual(Object.keys(state).sort(), ["apiKeyCreatedSecret", "apiKeyError", "apiKeyExpiresAt", "apiKeyLoading", "apiKeyName",
    "apiKeyScopes", "apiKeyUser", "apiKeys", "closeApiKeyDialog", "createApiKey", "loadUserApiKeys", "revokeApiKey", "setApiKeyExpiresAt",
    "setApiKeyName", "setApiKeyScopes"]);
  await act(async () => { await state.loadUserApiKeys({ id: "u1" }); });
  assert.deepEqual(plain(state.apiKeys), [{ id: "k1", name: "old" }]);
  assert.equal(state.apiKeyLoading, null);
  act(() => { state.setApiKeyName("ci"); state.setApiKeyScopes(" read, ,write "); state.setApiKeyExpiresAt("2030-01-02T00:00:00Z"); });
  let prevented = 0;
  await act(async () => { await state.createApiKey({ preventDefault: () => { prevented += 1; } }); });
  assert.equal(prevented, 1);
  assert.deepEqual(calls[1], ["POST", "/admin/chat/api/panel/users/u1/api-keys", { name: "ci", scopes: ["read", "write"], expires_at: "2030-01-02T00:00:00.000Z" }]);
  assert.equal(state.apiKeyCreatedSecret, "secret-1");
  assert.deepEqual(plain(state.apiKeys).map((key) => key.id), ["k2", "k1"]);
  assert.deepEqual([state.apiKeyName, state.apiKeyScopes, state.apiKeyExpiresAt], ["", "", ""]);
  await act(async () => { await state.revokeApiKey({ id: "k1", name: "old" }); });
  assert.equal(calls.length, 2, "no revoke without a confirm");
  confirmAnswer = true;
  await act(async () => { await state.revokeApiKey({ id: "k1", name: "old" }); });
  assert.deepEqual(calls[2], ["DELETE", "/admin/chat/api/panel/users/u1/api-keys/k1", null]);
  assert.equal(plain(state.apiKeys)[1].revoked, true);
  const failing = async () => { throw new Error("boom"); };
  let other;
  const Failing = () => { other = useAdminUserApiKeys(failing); return null; };
  await createAsync(createElement(Failing));
  await act(async () => { await other.loadUserApiKeys({ id: "u2" }); });
  assert.equal(other.apiKeyError, "boom");
  act(() => state.closeApiKeyDialog());
  assert.deepEqual([state.apiKeyUser, plain(state.apiKeys), state.apiKeyCreatedSecret, state.apiKeyError], [null, [], null, null]);
});

test("the role actions create, update and delete roles and report failures", async () => {
  const { createAdminRoleActions } = load("admin/components/usersTab/adminRoleActions.ts");
  const log = [];
  let roles = [{ id: "r2", name: "zeta", permissions: [] }];
  const set = (name) => (value) => log.push([name, typeof value === "function" ? "fn" : value]);
  const asked = [];
  let fail = false;
  const readJson = async (url, init = {}) => {
    log.push(["call", init.method ?? "GET", url, init.body ? JSON.parse(init.body) : null]);
    if (fail) throw new Error("nope");
    return { id: init.method === "POST" ? "r1" : "r2", name: init.method === "POST" ? "alpha" : "zeta", description: "d", permissions: [] };
  };
  const deps = { readJson, ask: (request) => asked.push(request), roleName: "alpha", roleDescription: "first",
    setRoles: (update) => { roles = update(roles); }, setRoleName: set("name"), setRoleDescription: set("description"),
    setRoleLoading: set("loading"), setRoleError: set("error"), setShowCreateRole: set("show") };
  const actions = createAdminRoleActions(deps);
  assert.deepEqual(Object.keys(actions), ["handleCreateRole", "handleUpdateRoleDescription", "handleUpdateRolePermissions", "handleDeleteRole"]);
  await actions.handleCreateRole({ preventDefault: noop });
  assert.deepEqual(plain(roles.map((role) => role.name)), ["alpha", "zeta"]);
  await actions.handleUpdateRoleDescription({ id: "r2" }, "new");
  await actions.handleUpdateRolePermissions({ id: "r2" }, ["chat"]);
  assert.deepEqual(plain(log), [
    ["loading", "create"], ["call", "POST", "/admin/chat/api/panel/roles", { name: "alpha", description: "first" }],
    ["name", ""], ["description", ""], ["error", null], ["show", false], ["loading", null],
    ["loading", "update:r2"], ["call", "PUT", "/admin/chat/api/panel/roles/r2", { description: "new" }], ["error", null], ["loading", null],
    ["loading", "permissions:r2"], ["call", "PUT", "/admin/chat/api/panel/roles/r2", { permissions: ["chat"] }], ["error", null], ["loading", null],
  ]);
  fail = true;
  log.length = 0;
  await actions.handleCreateRole({ preventDefault: noop });
  await actions.handleUpdateRoleDescription({ id: "r2" }, "x");
  await actions.handleUpdateRolePermissions({ id: "r2" }, []);
  assert.deepEqual(log.filter((entry) => entry[0] === "error").map((entry) => entry[1]), ["nope", "nope", "nope"]);
  fail = false;
  actions.handleDeleteRole({ id: "r1", name: "alpha" });
  assert.deepEqual([asked[0].title, asked[0].confirmLabel, asked[0].done], ["Delete role alpha?", "Delete alpha", "Role alpha deleted."]);
  await asked[0].run();
  assert.deepEqual(plain(roles.map((role) => role.id)), ["r2"]);
});

const botRow = (id, settings) => ({ id, name: `acme/${id}`, repository: `github:acme/${id}`, settings });

test("the PR review bot shows one card per repository with trigger, status, drafts, branches, limits and actions", async () => {
  const srv = server((call) => {
    if (call.url.endsWith("/pr-review-bot") && call.method === "GET" && !call.url.includes("/repositories/")) {
      return { status: 200, body: { repositories: [botRow("pay", { trigger: "pull_request", protected_branches: ["main"], review_drafts: false, status_policy: "gate" }),
        botRow("web", { trigger: "off" })], can_edit: true, webhook_configured: false } };
    }
    return { status: 404, body: {} };
  });
  const { PrReviewBotSection } = load("admin/components/projectsTab/repositories/PrReviewBotSection.tsx", { fetch: srv.fetch });
  const view = await createAsync(createElement(PrReviewBotSection, { workspaceId: "w1" }));
  await tick();
  const page = text(view.root);
  includesAll(page, ["PR review bot", "acme/pay", "acme/web", "Review pull requests", "Status on the pull request", "Review drafts", "Protected branches"]);
  assert.equal(byTestId(view, "review-bot-repo").length, 2);
  assert.equal(byTestId(view, "review-bot-pay-gate-hint").length, 1);
  assert.equal(byTestId(view, "review-bot-pay-webhook").length, 1);
  assert.equal(byTestId(view, "review-bot-pay-save").length, 0);
  await act(async () => { byTestId(view, "review-bot-pay-drafts")[0].props.onChange({ target: { checked: true } }); });
  assert.equal(byTestId(view, "review-bot-pay-save").length, 1);
  assert.ok(buttons(view).includes("Discard"));
  act(() => view.unmount());

  const empty = server((call) => (call.url.endsWith("/w2/pr-review-bot") ? { status: 200, body: { repositories: [], can_edit: false } } : { status: 404, body: {} }));
  const { PrReviewBotSection: Empty } = load("admin/components/projectsTab/repositories/PrReviewBotSection.tsx", { fetch: empty.fetch });
  const none = await createAsync(createElement(Empty, { workspaceId: "w2" }));
  assert.equal(byTestId(none, "review-bot-empty").length, 1);
  act(() => none.unmount());
  const gone = server(() => ({ status: 404, body: { detail: "Not Found" } }));
  const { PrReviewBotSection: Gone } = load("admin/components/projectsTab/repositories/PrReviewBotSection.tsx", { fetch: gone.fetch });
  const missing = await createAsync(createElement(Gone, { workspaceId: "w3" }));
  assert.equal(missing.toJSON(), null);
});

test("the answer feedback panel shows filters, the summaries and one row per feedback", async () => {
  const srv = server((call) => (call.url.includes("/summary")
    ? { status: 200, body: { total: 2, good: 1, bad: 1, by_workflow: [{ workflow_key: "fix", good: 1, bad: 0 }, { workflow_key: null, good: 0, bad: 1 }],
      by_aspect: [{ aspect: "sources", liked: 1, disliked: 0 }] } }
    : { status: 200, body: { items: [
      { id: "f1", rating: "good", liked: "Clear", disliked: "", aspects: { sources: "liked", speed: "disliked" }, workflow_key: "fix", execution_profile_id: "ep",
        session_link: "/chat/s1", message_id: "m1", provider: "p", model: "m", recorded_by: "anna", updated_at: "2026-01-02T00:00:00Z", memory_state: "kept" },
      { id: "f2", rating: "bad", liked: "", disliked: "", aspects: {}, workflow_key: null, memory_state: "forgotten" },
    ] } }));
  const { KnowledgeFeedbackPanel } = load("admin/components/workspaceKnowledge/KnowledgeFeedbackPanel.tsx", { fetch: srv.fetch });
  const view = await createAsync(createElement(KnowledgeFeedbackPanel, { workspaceId: "w1" }));
  includesAll(text(view.root), ["Answer feedback: people rate answers", "All ratings", "All aspects", "All workflows", "Refresh", "All (2)",
    "(no workflow)", "Sources", "Good: Clear", "+ Sources", "− Speed", "Open session", "p · m", "anna · 2026-01-02", "Forgotten: the texts were erased."]);
  assert.equal(all(view, "table").length, 3);
  assert.equal(all(view, "select").length, 3);
  assert.deepEqual(all(view, "select")[2].findAll((node) => node.type === "option").map((node) => node.props.value), ["", "fix"]);
  await act(async () => { all(view, "select")[0].props.onChange({ target: { value: "bad" } }); });
  assert.ok(srv.calls.at(-1).url.includes("rating=bad"));
  const none = server((call) => (call.url.includes("/summary") ? { status: 500, body: { detail: "down" } } : { status: 200, body: { items: [] } }));
  const { KnowledgeFeedbackPanel: Empty } = load("admin/components/workspaceKnowledge/KnowledgeFeedbackPanel.tsx", { fetch: none.fetch });
  const empty = await createAsync(createElement(Empty, { workspaceId: "w1" }));
  assert.equal(all(empty, "table").length, 0);
  assert.equal(empty.root.findAll((node) => node.props.role === "status").length, 1);
});

test("the model catalog sync drawer lists new, gone and unaliased models with their actions", async () => {
  const srv = server((call) => (call.url.endsWith("/sync") ? { status: 200, body: {
    new: [{ provider_id: "p1", provider: "OpenAI", model_id: "gpt-x", supports_tools: true, context_length: 128000 }, { provider_id: "p1", model_id: "gpt-y" }],
    gone: [{ id: "g1", display_name: "Old", enabled: true, used_by_workspaces: 2, order_position: 3 }, { id: "g2", display_name: "Off", enabled: false }],
    gateway_without_alias: [{ id: "a1", display_name: "Raw" }], providers: [{ provider: "Down", state: "failed" }],
  } } : { status: 200, body: {} }));
  const { ModelCatalogSyncDrawer } = load("admin/components/modelCatalog/ModelCatalogSyncDrawer.tsx", { fetch: srv.fetch });
  let changed = 0;
  const view = await createAsync(createElement(ModelCatalogSyncDrawer, { onClose: noop, onChanged: () => { changed += 1; } }));
  includesAll(text(view.root), ["Sync from providers", "Could not reach: Down.", "New upstream (added, not enabled)", "gpt-x", "OpenAI · tools · 128k context",
    "Gone upstream", "Enabled, used by 2 Workspaces, order #3.", "Not enabled, used by 0 Workspaces, not in the platform order.", "Gateway", "Raw",
    "Served by the gateway but has no alias"]);
  assert.equal(changed, 1);
  assert.deepEqual(buttons(view), ["", "Disable", "Add to catalog", "Close", "Add selected"]);
  assert.equal(byTestId(view, "sync-add-selected")[0].props.disabled, true);
  await act(async () => { all(view, "input")[0].props.onChange({ target: { checked: true } }); });
  assert.equal(byTestId(view, "sync-add-selected")[0].props.disabled, false);
  await act(async () => { await byTestId(view, "sync-add-selected")[0].props.onClick(); });
  await tick();
  includesAll(text(view.root), ["1 model added to the catalog (not enabled)."]);
  assert.equal(all(view, "input").length, 1);
  await act(async () => { all(view, "button").find((node) => text(node) === "Add to catalog").props.onClick(); });
  await tick();
  includesAll(text(view.root), ["Every gateway model has an alias.", "Alias created (not enabled)."]);
  const failing = server(() => ({ status: 500, body: { detail: "down" } }));
  const { ModelCatalogSyncDrawer: Failing } = load("admin/components/modelCatalog/ModelCatalogSyncDrawer.tsx", { fetch: failing.fetch });
  const broken = await createAsync(createElement(Failing, { onClose: noop, onChanged: noop }));
  assert.equal(broken.root.findAll((node) => node.props.role === "alert").length, 1);
  assert.equal(all(broken, "section").length, 0);
});

test("the knowledge changes panel asks for a version range and lists the cited facts", async () => {
  const srv = server((call) => {
    if (call.url.endsWith("/graph")) return { status: 200, body: { episodes: 12, pending_revisions: 3 } };
    if (call.url.endsWith("/changes")) return { status: 200, body: { state: "ok", episodes: 4, versions: ["3.5", "4.0"], facts_workspace: "Lib",
      facts: [{ relation: "removed", version: "4.0", fact: "X was removed", citation: "c1", source_title: "Notes", source_url: "https://n.test", section: "s" }] } };
    return { status: 200, body: {} };
  });
  const { KnowledgeChangesPanel } = load("admin/components/workspaceKnowledge/KnowledgeChangesPanel.tsx", { fetch: srv.fetch });
  const view = await createAsync(createElement(KnowledgeChangesPanel, { workspaceId: "w1" }));
  includesAll(text(view.root), ["What changed between two versions", "Show changes", "Only typed change records", "Knowledge graph",
    "12 extracted sections · 3 revisions still being extracted", "Extract spring-boot 4.0 into the graph", "Refresh"]);
  assert.deepEqual(all(view, "input").map((node) => node.props.value ?? node.props.checked), ["spring-boot", "3.5", "4.0", "", true]);
  await act(async () => { await all(view, "form")[0].props.onSubmit({ preventDefault: noop }); });
  includesAll(text(view.root), ["1 facts from 4 extracted sections, versions 3.5, 4.0, from the Workspace “Lib”.", "removed", "4.0 · ", "X was removed"]);
  assert.deepEqual(srv.calls.find((call) => call.url.endsWith("/changes")).body,
    { product: "spring-boot", from_version: "3.5", to_version: "4.0", query: null, limit: 100, changes_only: true });
  const missing = server(() => ({ status: 500, body: { detail: "x" } }));
  const { KnowledgeChangesPanel: Missing } = load("admin/components/workspaceKnowledge/KnowledgeChangesPanel.tsx", { fetch: missing.fetch });
  const none = await createAsync(createElement(Missing, { workspaceId: "w1" }));
  assert.ok(text(none.root).includes("Graph status unavailable."));
});

test("the documentation target card shows the stored target to an admin and read-only to a member", async () => {
  const config = { config: { feature_documentation: { confluence_space_key: "eng", parent_page_id: "", knowledge_connector_key: "gone", auto_publish: true } } };
  const srv = server((call) => {
    if (call.url.endsWith("/config")) return { status: 200, body: config };
    if (call.url.includes("connectors")) return { status: 200, body: { connectors: [{ connector_key: "conf", kind: "confluence", scope: { spaces: ["eng", "ops"] } }] } };
    return { status: 200, body: [] };
  });
  const { WorkspaceDocumentationTargetCard } = load("admin/components/workspaceSettings/WorkspaceDocumentationTargetCard.tsx", { fetch: srv.fetch, performance });
  const view = await createAsync(createElement(WorkspaceDocumentationTargetCard, { projectId: "p1", isAdmin: true }));
  await tick();
  includesAll(text(view.root), ["Documentation target", "Space key", "The key in the space's address", "Parent page id", "(required)",
    "Knowledge source", "Automatic: the source that covers the space", "gone (no longer a Confluence source)", "Publish automatically"]);
  assert.equal(byTestId(view, "doc-target-space")[0].props.value, "ENG");
  assert.equal(byTestId(view, "doc-target-parent-warning").length, 1);
  assert.equal(byTestId(view, "doc-target-readonly").length, 0);
  assert.equal(byTestId(view, "doc-target-save").length, 0);
  await act(async () => { byTestId(view, "doc-target-parent")[0].props.onChange({ target: { value: "123" } }); });
  assert.equal(byTestId(view, "doc-target-save").length, 1);
  assert.ok(buttons(view).includes("Discard"));
  act(() => view.unmount());

  const member = server((call) => (call.url.endsWith("/api/v1/projects") ? { status: 200, body: [{ id: "p1", config: {} }] } : { status: 200, body: { connectors: [] } }));
  const { WorkspaceDocumentationTargetCard: Member } = load("admin/components/workspaceSettings/WorkspaceDocumentationTargetCard.tsx", { fetch: member.fetch, performance });
  const readOnly = await createAsync(createElement(Member, { projectId: "p1", isAdmin: false }));
  await tick();
  assert.equal(byTestId(readOnly, "doc-target-readonly").length, 1);
  assert.equal(byTestId(readOnly, "doc-target-space")[0].props.disabled, true);
  act(() => readOnly.unmount());
  const broken = server(() => ({ status: 500, body: {} }));
  const { WorkspaceDocumentationTargetCard: Broken } = load("admin/components/workspaceSettings/WorkspaceDocumentationTargetCard.tsx", { fetch: broken.fetch, performance });
  const failed = await createAsync(createElement(Broken, { projectId: "p1", isAdmin: true }));
  await tick();
  assert.equal(text(failed.root), "The documentation target could not be loaded.");
});

test("the providers list shows one row per provider and opens a row in the side panel", async () => {
  const srv = server(() => ({ status: 200, body: { is_active: false } }));
  const { ProvidersList } = load("admin/components/providerTab/ProvidersList.tsx", { fetch: srv.fetch });
  const toggled = [];
  const providers = [{ id: "p1", display_name: "Team gateway", driver: "litellm_gateway", is_active: true, readiness: { state: "ready" } },
    { id: "p2", display_name: "Lab gateway", driver: "litellm_gateway", is_active: false, readiness: { state: "unknown" } }];
  const ctx = { providers, expandedProvider: null, handleDeleteProvider: noop, handleUpdateLiteLlmGatewayProvider: noop,
    handleToggleProvider: (id) => toggled.push(id) };
  const view = await createAsync(createElement(ProvidersList, { ctx }));
  includesAll(text(view.root), ["Name", "Connection", "State", "Enabled", "Team gateway", "Lab gateway", "Model gateway"]);
  assert.equal(byTestId(view, "providers-table").length, 1);
  assert.equal(byTestId(view, "provider-card-p1").length, 1);
  assert.notEqual(byTestId(view, "provider-enabled-p2")[0].props["aria-disabled"], true);
  assert.equal(byTestId(view, "provider-panel").length, 0);
  await act(async () => { byTestId(view, "provider-enabled-p1")[0].props.onClick({ stopPropagation: noop }); });
  await tick();
  assert.deepEqual(srv.calls.map((call) => [call.method, call.url, call.body]), [["PUT", "/admin/chat/api/panel/providers/p1", { is_active: false }]]);
  act(() => view.unmount());
  const opened = await createAsync(createElement(ProvidersList, { ctx: { ...ctx, expandedProvider: "p2" } }));
  assert.equal(byTestId(opened, "provider-panel").length, 1);
  assert.equal(byTestId(opened, "provider-panel-footer").length, 1);
  const none = await createAsync(createElement(ProvidersList, { ctx: { ...ctx, providers: [] } }));
  assert.ok(text(none.root).includes("No providers configured yet."));
});
