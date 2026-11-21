// Render guards for admin skill and connection forms split into smaller functions: a skill's versions with diff,
// roll back and retire, the skill import drawer, a Workspace's narrowing of one connection, and the identity provider
// panel render the same structure.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, noop, plain, testIds } from "./adminGuardRenderers.mjs";
import { jsonRoutes, loadStubbed, stubs } from "./adminGuardStubLoader.mjs";

const version = (version, state, patch = {}) => ({ id: `v${version}`, version, state, note: "", author_name: "Ann", reviewer_name: null,
  approval_mode: null, upstream: null, created_at: "2026-01-02T03:04:05Z", published_at: null, retired_at: null, ...patch });

test("the skill versions tab lists versions with diff, roll back and a confirmed retire", async () => {
  const calls = [];
  const api = {
    loadDiff: async (...args) => { calls.push(["diff", ...args]); return { against: 3, files: [
      { path: "SKILL.md", status: "modified", added: 2, removed: 1 }, { path: "x", status: "unchanged", added: 0, removed: 0 }] }; },
    rollbackVersion: async (...args) => { calls.push(["rollback", ...args]); },
    retireVersion: async (...args) => { calls.push(["retire", ...args]); },
  };
  const { SkillVersionsTab } = loadStubbed("admin/components/skillCatalog/SkillVersionsTab.tsx", ["./SkillDiff"], {}, { "./skillCatalogApi": api });
  const changed = [];
  const detail = { id: "sk1", published: version(3, "published"), versions: [
    version(4, "draft", { note: "Tighter" }), version(3, "published", { reviewer_name: "Bob", approval_mode: "self", upstream: { commit: "abcdef1234" },
      published_at: "2026-01-03T00:00:00Z" }), version(2, "retired", { retired_at: "2026-01-04T00:00:00Z", reviewer_name: "Cleo" })] };
  const view = create(createElement(SkillVersionsTab, { detail, onChanged: async (message) => { changed.push(message); } }));
  includesAll(text(view.root), ["Version", "Author → approver", "v4", "Tighter", "pending", "Bob (self-approved)", "abcdef12", "created 2026-01-02 03:04",
    "published 2026-01-03 00:00", "retired 2026-01-04 00:00", "Draft", "Published", "Retired", "Roll back to this version", "Retire",
    "Same lifecycle as platform policies"]);
  assert.deepEqual(testIds(view), ["skill-versions", "skill-version-4", "skill-version-diff-4", "skill-version-3", "skill-version-retire",
    "skill-version-2", "skill-version-diff-2", "skill-version-rollback-2"]);
  assert.equal(all(view, "tr").length, 4);
  await act(async () => byTestId(view, "skill-version-diff-4")[0].props.onClick());
  await tick();
  assert.deepEqual(calls[0], ["diff", "sk1", 4, "published"]);
  includesAll(text(byTestId(view, "skill-version-diff")[0]), ["v4 against published v3", "Close", "SKILL.md", "modified", "+2 −1"]);
  assert.equal(stubs(view, "SkillDiff").length, 1);
  act(() => byTestId(view, "skill-version-retire")[0].props.onClick());
  assert.ok(text(view.root).includes("Retiring v3 stops its delivery in every Workspace"));
  assert.deepEqual(buttons(view).filter((label) => label === "Retire v3" || label === "Cancel"), ["Retire v3", "Cancel"]);
  await act(async () => byTestId(view, "skill-version-retire-confirm")[0].props.onClick());
  await tick();
  assert.deepEqual(changed, ["v3 retired."]);
  assert.equal(byTestId(view, "skill-version-retire").length, 1);
  await act(async () => byTestId(view, "skill-version-rollback-2")[0].props.onClick());
  assert.deepEqual(calls.at(-1), ["rollback", "sk1", 2]);

  const unpublished = create(createElement(SkillVersionsTab, { detail: { id: "s", published: null, versions: [version(1, "draft")] }, onChanged: async () => {} }));
  assert.deepEqual(testIds(unpublished), ["skill-versions", "skill-version-1"]);
});

test("the skill import drawer switches modes and offers upload, inspect and import", async () => {
  const calls = [];
  const api = {
    importUpload: async (...args) => { calls.push(["upload", ...args]); return { imported: [{ id: "k1" }] }; },
    inspectSource: async (body) => { calls.push(["inspect", body]); return { url: "https://git/x", commit: "c", skills: [], mcp_servers: [] }; },
    loadSources: async () => ({ sources: [] }),
    importFromGit: async (body) => { calls.push(["git", body]); return { imported: [] }; },
  };
  const { SkillImportDrawer } = loadStubbed("admin/components/skillCatalog/SkillImportDrawer.tsx",
    ["../projectsTab/SettingsDrawer", "./SkillImportGit", "./SkillImportResults", "./SkillImportUpload"], {}, { "./skillCatalogApi": api });
  const imported = [];
  const view = create(createElement(SkillImportDrawer, { categories: { categories: [] }, onClose: noop, onImported: (ids) => imported.push(ids) }));
  const drawer = stubs(view, "SettingsDrawer")[0];
  assert.deepEqual([drawer.props.eyebrow, drawer.props.title, drawer.props.size], ["Skills", "Import skill", "detail"]);
  includesAll(text(view.root), ["Upload", "Git repository", "Marketplace", "Cancel", "Import as draft"]);
  assert.deepEqual(testIds(view), ["skill-import-drawer", "skill-import-mode-upload", "skill-import-mode-git", "skill-import-mode-market",
    "skill-import-upload"]);
  assert.equal(stubs(view, "SkillImportUpload").length, 1);
  assert.equal(byTestId(view, "skill-import-upload")[0].props.disabled, true);
  act(() => stubs(view, "SkillImportUpload")[0].props.onFile({ name: "SKILL.md", size: 10 }));
  act(() => stubs(view, "SkillImportUpload")[0].props.onCategory("c1"));
  assert.equal(byTestId(view, "skill-import-upload")[0].props.disabled, false);
  await act(async () => byTestId(view, "skill-import-upload")[0].props.onClick());
  await tick();
  assert.equal(calls[0][0], "upload");
  act(() => byTestId(view, "skill-import-mode-git")[0].props.onClick());
  assert.equal(stubs(view, "SkillImportGit")[0].props.mode, "git");
  assert.equal(byTestId(view, "skill-import-inspect")[0].props.disabled, true);
  act(() => stubs(view, "SkillImportGit")[0].props.onChange({ url: "https://git/x" }));
  await act(async () => byTestId(view, "skill-import-inspect")[0].props.onClick());
  await tick();
  assert.equal(calls[1][0], "inspect");
  assert.equal(stubs(view, "SkillImportResults").length, 1);
  includesAll(text(view.root), ["Back"]);
  assert.equal(byTestId(view, "skill-import-git")[0].props.disabled, true);
  act(() => all(view, "button").find((node) => text(node) === "Back").props.onClick());
  assert.equal(stubs(view, "SkillImportGit").length, 1);
});

const connection = (patch) => ({ id: "c1", name: "Confluence", type: "confluence", state: "ok", can_edit: true, deviation: null,
  base: { knowledge: { enabled: true, scope: { spaces: ["ENG", "OPS"] } }, tickets: { enabled: false }, agent_tools: { level: "write" } },
  effective: { knowledge: { enabled: true, scope: { spaces: ["ENG", "OPS"] } }, tickets: { enabled: false }, agent_tools: { level: "write" } }, ...patch });

test("a Workspace narrows one connection and saves or resets its deviation", async () => {
  const { readJson, calls } = jsonRoutes({ "/api/v1/workspaces/": (init) => (init.method === "DELETE" ? { deviation: null } : { deviation: { knowledge: {} } }) });
  const { WorkspaceConnectionNarrow } = loadStubbed("admin/components/projectsTab/WorkspaceConnectionNarrow.tsx", [], {}, { "/adminPanelHelpers": { readJson } });
  const saved = [];
  const view = create(createElement(WorkspaceConnectionNarrow, { workspaceId: "w1", workspaceName: "Harbor", connection: connection(), onSaved: (next) => saved.push(next) }));
  includesAll(text(view.root), ["Confluence", "Inherited from global", "Uses the global connection in Harbor", "Knowledge sync", "Inherited",
    "Use it in this workspace", "Spaces", "ENG", "OPS", "Only the 2 the global connection allows are listed.", "Tickets", "Switched off globally.",
    "Agent tools", "Agents may read and write (with approval)", "Writing needs approval by the global rule", "Save for Harbor"]);
  assert.equal(all(view, "fieldset").length, 3);
  assert.equal(all(view, "option").length, 3);
  const save = () => all(view, "button").find((node) => text(node) === "Save for Harbor");
  assert.equal(save().props.disabled, true);
  const boxes = () => all(view, "input");
  act(() => boxes()[1].props.onChange({ target: { checked: false } }));
  act(() => boxes()[2].props.onChange({ target: { checked: false } }));
  assert.ok(text(view.root).includes("Knowledge sync: pick at least one, or switch it off."));
  act(() => boxes()[1].props.onChange({ target: { checked: true } }));
  assert.equal(save().props.disabled, false);
  await act(async () => save().props.onClick());
  await tick();
  assert.deepEqual(plain(calls[0]), { url: "/api/v1/workspaces/w1/connections/c1/deviation", method: "PUT", body: { knowledge: { scope: { spaces: ["ENG"] } } } });
  assert.equal(saved.length, 1);
  assert.ok(text(view.root).includes("Saved."));

  const narrowed = create(createElement(WorkspaceConnectionNarrow, { workspaceId: "w1", connection: connection({ deviation: { agent_tools: { level: "read" } },
    effective: { agent_tools: { level: "read" } } }), onSaved: noop }));
  includesAll(text(narrowed.root), ["1 change from global", "this workspace", "Narrowed", "Reset to global"]);
  assert.equal(all(narrowed, "details")[0].props.open, true);
  await act(async () => all(narrowed, "button").find((node) => text(node) === "Reset to global").props.onClick());
  await tick();
  assert.equal(calls.at(-1).method, "DELETE");
  assert.ok(text(narrowed.root).includes("Reset to global."));
  const readOnly = create(createElement(WorkspaceConnectionNarrow, { workspaceId: "w1", connection: connection({ can_edit: false }), onSaved: noop }));
  assert.ok(text(readOnly.root).includes("Only a workspace admin can narrow it."));
  assert.equal(all(readOnly, "fieldset")[0].props.disabled, true);
  assert.deepEqual(buttons(readOnly), []);
});

test("the identity provider panel edits the provider, claims, new users and group mappings", () => {
  const { IdentityProviderPanel } = loadStubbed("admin/components/usersTab/IdentityProviderPanel.tsx", ["/SidePanel", "/FormSection", "./GroupMappingEditor"]);
  const draft = { name: "Corp", issuerUrl: "https://idp", discoveryUrl: "", clientId: "cid", scopes: "openid", isActive: true,
    claimMappings: { email: "mail" }, autoProvisionUsers: false, defaultRoles: new Set(["dev"]), defaultGroupIds: new Set(),
    groupRoleMappings: [{ external: "eng", values: ["dev"] }], groupGroupMappings: [] };
  const updates = [];
  const saved = [];
  const provider = { id: "p1", name: "Corp SSO", providerType: "oidc", issuerUrl: "" };
  const view = create(createElement(IdentityProviderPanel, { provider, draft, roles: [{ id: "r1", name: "dev" }, { id: "r2", name: "ops" }],
    groups: [{ id: "g1", name: "Team" }], saving: false, onUpdateDraft: (id, updater) => updates.push([id, updater(draft)]),
    onSave: (row) => saved.push(row.id), onClose: noop }));
  const panel = stubs(view, "SidePanel")[0];
  assert.deepEqual([panel.props.title, panel.props.subtitle, panel.props.testId], ["Corp SSO", "OIDC · issuer not set", "oidc-provider-panel"]);
  assert.deepEqual(stubs(view, "FormSection").map((node) => node.props.title), ["Provider", "Claim mappings", "New users", "Group mappings"]);
  includesAll(text(view.root), ["Active", "Provider name", "Issuer URL", "Discovery URL", "Client ID", "Scopes", "Subject claim", "Email claim",
    "Username claim", "Display-name claim", "Groups claim", "Create users at their first sign-in", "Default roles", "dev", "ops",
    "Default groups", "Team", "Cancel", "Save changes"]);
  assert.equal(all(view, "input").length, 1 + 5 + 5 + 1 + 2 + 1);
  assert.deepEqual(all(view, "input").filter((node) => node.props.type === "checkbox").map((node) => node.props.checked), [true, false, true, false, false]);
  const mappings = stubs(view, "GroupMappingEditor");
  assert.deepEqual(mappings.map((node) => node.props.testId), ["provider-role-mappings-p1", "provider-group-mappings-p1"]);
  assert.deepEqual(plain(mappings[1].props.options), [{ value: "g1", label: "Team" }]);
  act(() => all(view, "input")[1].props.onChange({ target: { value: "New" } }));
  act(() => all(view, "input")[8].props.onChange({ target: { value: "upn" } }));
  act(() => all(view, "input")[13].props.onChange({ target: { checked: true } }));
  act(() => mappings[1].props.onChange([{ external: "x", values: ["g1"] }]));
  assert.equal(updates[0][1].name, "New");
  assert.deepEqual(plain(updates[1][1].claimMappings), { email: "mail", username: "upn" });
  assert.deepEqual([...updates[2][1].defaultRoles], ["dev", "ops"]);
  assert.equal(updates[3][1].groupGroupMappings.length, 1);
  act(() => byTestId(view, "oidc-provider-save")[0].props.onClick());
  assert.deepEqual(saved, ["p1"]);
});
