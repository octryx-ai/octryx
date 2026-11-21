// Render guards for admin parts split into smaller functions: a Workspace's quality and repository bootstrap forms,
// the governed gateway section of a provider, a skill import's inspect result, skill usage, a Workspace's agent
// assignment and the role catalog render the same structure and pass the same props.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, text } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, plain } from "./adminGuardRenderers.mjs";
import { loadStubbed, stubs } from "./adminGuardStubLoader.mjs";
import { button, hostCount } from "./adminGuardTreeReaders.mjs";

test("the quality policies section hands the context to the quality and the repository bootstrap forms", () => {
  const { ProjectQualityPoliciesSection } = loadStubbed("admin/components/projectsTab/ProjectQualityPoliciesSection.tsx",
    ["./policies/ProjectRepoQualityForm", "./policies/ProjectRepositoryBootstrapForm"]);
  const names = ["configuringProjectQuality", "handleSaveProjectQuality", "projectQualityDraft", "setProjectQualityDraft", "projectQualityError",
    "projectQualityLoading", "handleSaveProjectRepositoryBootstrap", "projectRepoBootstrapProvider", "setProjectRepoBootstrapProvider",
    "projectRepoBootstrapDefaultBranch", "setProjectRepoBootstrapDefaultBranch", "projectRepoBootstrapDefaultRepoName",
    "setProjectRepoBootstrapDefaultRepoName", "projectRepoBootstrapWorkspaceSubdir", "setProjectRepoBootstrapWorkspaceSubdir",
    "projectRepoBootstrapRemoteVisibility", "setProjectRepoBootstrapRemoteVisibility", "projectRepoBootstrapGithubOwner",
    "setProjectRepoBootstrapGithubOwner", "projectRepoBootstrapGithubOwnerType", "setProjectRepoBootstrapGithubOwnerType",
    "projectRepoBootstrapBitbucketProjectKey", "setProjectRepoBootstrapBitbucketProjectKey", "projectRepoBootstrapEnabled",
    "setProjectRepoBootstrapEnabled", "projectRepoBootstrapAutoOnSessionStart", "setProjectRepoBootstrapAutoOnSessionStart",
    "handleClearProjectRepositoryBootstrap"];
  const ctx = Object.fromEntries(names.map((name) => [name, `v:${name}`]));
  const view = create(createElement(ProjectQualityPoliciesSection, { ctx }));
  const describe = (name) => Object.entries(stubs(view, name)[0].props).filter(([key]) => key !== "children").map(([key, value]) => `${key}=${value}`).sort();
  assert.deepEqual(describe("ProjectRepoQualityForm"), ["onSubmit=v:handleSaveProjectQuality", "projectQualityDraft=v:projectQualityDraft",
    "projectQualityError=v:projectQualityError", "projectQualityLoading=v:projectQualityLoading", "setProjectQualityDraft=v:setProjectQualityDraft"]);
  const bootstrap = describe("ProjectRepositoryBootstrapForm");
  assert.equal(bootstrap.length, 23);
  for (const name of names.filter((key) => key.includes("RepoBootstrap"))) assert.ok(bootstrap.includes(`${name}=v:${name}`), name);
  includesAll(bootstrap.join(" "), ["onSubmit=v:handleSaveProjectRepositoryBootstrap", "onUseImplicitLocalFallback=v:handleClearProjectRepositoryBootstrap",
    "projectQualityLoading=v:projectQualityLoading"]);
  assert.equal(hostCount(view), 2);
});

test("the gateway section shows the state, the fields, and resets or saves the draft", async () => {
  const updates = [];
  const contract = {
    gatewayDraftFromProvider: () => ({ ok: false, name: "stored" }),
    isGatewayDraftSubmittable: (draft) => draft.ok,
    buildGatewayUpdatePayload: (draft, config) => ({ draft, config }),
  };
  let answer = { ok: false, error: "Refused" };
  const ctx = { handleUpdateLiteLlmGatewayProvider: async (...args) => { updates.push(args); return answer; } };
  const { ProviderLiteLlmGatewaySection } = loadStubbed("admin/components/providerTab/ProviderLiteLlmGatewaySection.tsx",
    ["/FormSection", "/PanelFooterSlot", "/StatusLabel", "./LiteLlmGatewayConfigFields", "./LiteLlmGatewaySecretNotice"], {},
    { "./litellmGatewayContract": contract, "./litellmGatewayDrafts": contract, "./litellmGatewayPayload": contract, "./litellmGatewayTypes": contract, "./litellmGatewayValidation": contract });
  const provider = { id: "p1", has_api_key: true, config_json: { a: 1 }, readiness_status: "blocked", readiness_reason: "x" };
  const view = create(createElement(ProviderLiteLlmGatewaySection, { ctx, provider }));
  assert.equal(stubs(view, "LiteLlmGatewaySecretNotice")[0].props.idPrefix, "litellm-gateway-p1");
  assert.equal(stubs(view, "LiteLlmGatewaySecretNotice")[0].props.secretRefConfigured, true);
  assert.equal(stubs(view, "FormSection")[0].props.title, "State");
  assert.equal(stubs(view, "StatusLabel")[0].props.tone, "neutral");
  assert.deepEqual(buttons(view), ["Reset", "Save changes"]);
  assert.equal(button(view, "Save changes").props.disabled, true);
  assert.equal(hostCount(view), 10);
  act(() => stubs(view, "LiteLlmGatewayConfigFields")[0].props.onChange({ ok: true, name: "edited" }));
  await act(async () => button(view, "Save changes").props.onClick());
  assert.deepEqual(plain(updates[0]), ["p1", { draft: { ok: true, name: "edited" }, config: { a: 1 } }]);
  includesAll(text(view.root), ["Refused"]);
  answer = { ok: true };
  await act(async () => button(view, "Save changes").props.onClick());
  includesAll(text(view.root), ["Saved. The state above updates with the next check."]);
  act(() => button(view, "Reset").props.onClick());
  assert.equal(stubs(view, "LiteLlmGatewayConfigFields")[0].props.draft.name, "stored");
  assert.equal(all(view, "p").filter((node) => node.props.role === "status").length, 1);
});

const item = (patch) => ({ kind: "skill", path: "skills/a", name: "a", files: 2, importable: true, existing: null,
  licence: { spdx: "MIT", source: "LICENSE", allowed: true }, ...patch });

test("the inspect result lists items, ignored parts, the import options and the security preview", () => {
  const toggled = [], set = [];
  const { SkillImportResults } = loadStubbed("admin/components/skillCatalog/SkillImportResults.tsx", ["./SkillImportUpload"]);
  const result = { url: "u", ref: "main", commit: "abcdef1234567", path: "", licence: { spdx: "MIT", source: "LICENSE" },
    plugin: { name: "kit", author: "Ann", description: "Tools" }, ignored: [{ path: "hooks/x", reason: "hooks are never imported" }],
    skills: [item({ scripts: ["run.sh"], execution_keys: ["allowed-tools"], description: "Does a", security: { high: 0, medium: 1, info: 2 } }),
      item({ name: "b", path: "skills/b", existing: { skill_id: "s", relation: "update", kind: "skill" }, files: ["x"] })],
    mcp_servers: [item({ kind: "mcp_server", name: "srv", path: "", importable: false, licence: { spdx: null, source: "", allowed: false },
      launch_spec: { command: "npx", args: ["srv"], image: "img", passthrough: ["TOKEN"] }, spec_issues: [{ code: "c", severity: "error", message: "Bad spec" }] })] };
  const props = { result, source: null, selected: ["skill:skills/a:a"], categoryId: "", tags: "", tracking: "pinned", trust: "",
    categories: { items: [] }, onToggle: (key) => toggled.push(key), onCategory() {}, onTags: (value) => set.push(value), onTracking: (value) => set.push(value),
    onTrust: (value) => set.push(value) };
  const view = create(createElement(SkillImportResults, props));
  includesAll(text(view.root), ["Plugin kit, author Ann · Tools · source /", "Commit abcdef1", "on main", "licence MIT (LICENSE)",
    "2 skills, 1 MCP server found.", "In the catalog", "MCP server", "· 2 files", "· 1 file", "No licence · not allowed",
    "run.sh · will be withheld", "stripped: allowed-tools", "security 0 high · 1 medium · 2 info", "Does a", "npx srv", "image img",
    "TOKEN: never passed through", "Bad spec", "Already in the catalog: use its update.", "Ignored (never imported):", "hooks/x",
    "Tracking", "Follow the branch (main)", "Trust of the new source", "Security review (preview)", "Imported entries start as drafts"]);
  assert.deepEqual(all(view, "input").filter((node) => node.props.type === "checkbox").map((node) => [node.props.checked, node.props.disabled]),
    [[true, false], [false, true], [false, true]]);
  assert.equal(stubs(view, "CategorySelect").length, 1);
  assert.equal(hostCount(view), 75);
  act(() => all(view, "input")[0].props.onChange());
  assert.deepEqual(toggled, ["skill:skills/a:a"]);
  act(() => all(view, "select")[0].props.onChange({ target: { value: "follow" } }));
  act(() => all(view, "select")[1].props.onChange({ target: { value: "official" } }));
  assert.deepEqual(set, ["follow", "official"]);
  const plainResult = { ...result, plugin: null, licence: null, ref: "HEAD", skills: [], mcp_servers: [], ignored: [] };
  const sourced = create(createElement(SkillImportResults, { ...props, result: plainResult, selected: [],
    source: { label: "Kit repo", trust: "official" } }));
  includesAll(text(sourced.root), ["no licence detected", "0 skills, 0 MCP servers found.", "Nothing to import", "(needs a branch or tag)",
    "Already a catalog source: Kit repo (official)."]);
});

test("the usage tab shows the KPIs, the per-skill rows and the unmanaged names, and opens a skill", async () => {
  const opened = [], periods = [];
  const usage = (days) => ({ days, totals: { uses: 9, refusals: 1 }, unmanaged: [{ name: "local", uses: 3 }],
    skills: [{ skill_id: "s1", name: "deploy", uses: 6, refusals: 0, last_used_at: null,
      by_surface: { "platform_chat:use": 4, "octryx_claude:model": 1, "octryx_claude:slash": 1 } },
    { skill_id: "s2", name: "srv", uses: 3, refusals: 0, last_used_at: null, by_surface: {} }] });
  const { SkillUsageTab } = loadStubbed("admin/components/skillCatalog/SkillUsageTab.tsx", [], {},
    { "./skillCatalogApi": { loadUsage: async (days) => { periods.push(days); return usage(days); } } });
  const rows = [{ id: "s1", kind: "skill", published: true }, { id: "s2", kind: "mcp_server", published: true }, { id: "s3", kind: "skill", published: true }];
  const view = await createAsync(createElement(SkillUsageTab, { rows, onOpenSkill: (...args) => opened.push(args) }));
  includesAll(text(view.root), ["Period", "Last 30 days", "Skill loads · 30 days", "9", "chat 4 · octryx-claude 2", "Skills in use", "2 / 3",
    "1 published entry unused for 30 days", "Refused by policy", "deploy", "1 / 1", "srv MCP", "Not from the catalog (unmanaged)", "local",
    "Only the skill name, version digest"]);
  assert.deepEqual(all(view, "th").map((node) => text(node)), ["Skill", "Platform chat", "octryx-claude (model / slash)", "Last used",
    "Skill name", "Uses"]);
  assert.equal(hostCount(view), 58);
  act(() => all(view, "tr").find((node) => node.props["data-testid"] === "usage-row-deploy").props.onKeyDown({ key: "Enter" }));
  assert.deepEqual(plain(opened), [["s1", "usage"]]);
  await act(async () => all(view, "select")[0].props.onChange({ target: { value: "7" } }));
  assert.deepEqual(periods, [30, 7]);
  const { SkillUsageTab: Empty } = loadStubbed("admin/components/skillCatalog/SkillUsageTab.tsx", [], {},
    { "./skillCatalogApi": { loadUsage: async () => ({ days: 30, totals: { uses: 0, refusals: 0 }, unmanaged: [], skills: [] }) } });
  includesAll(text((await createAsync(createElement(Empty, { rows: [], onOpenSkill() {} }))).root), ["No catalog skill was used in this period."]);
});

test("the agent assignment panel offers the mode and the enabled agents and saves both", async () => {
  const saved = [];
  const { WorkspaceAssignmentControlsPanel } = loadStubbed(
    "admin/components/projectsTab/workspaceComposition/WorkspaceAssignmentControlsPanel.tsx", []);
  const bindings = [
    { binding_key: "dev", display_name: "Developer", capability_kind: "agent", is_enabled: true, binding_status: "active" },
    { binding_key: "hid", display_name: "", capability_kind: "agent", is_enabled: true, binding_status: "hidden" },
    { binding_key: "ops", display_name: "", capability_kind: "agent", is_enabled: true, binding_status: "active" },
    { binding_key: "tool", display_name: "Tool", capability_kind: "tool", is_enabled: true, binding_status: "active" },
  ];
  const props = { controls: { agent_assignment_mode: "weird", default_agent_binding_key: "ops" }, bindings, view: "agents", isSaving: false,
    onSave: async (patch) => saved.push(patch) };
  const view = create(createElement(WorkspaceAssignmentControlsPanel, props));
  includesAll(text(view.root), ["Agent assignment", "all_installed", "Agent mode", "Default agent", "No explicit default",
    "Developer (dev)", "ops (ops)", "Save assignment", "enabled choices: 2"]);
  assert.equal(hostCount(view), 23);
  act(() => all(view, "select")[0].props.onChange({ target: { value: "selected_only" } }));
  await act(async () => button(view, "Save assignment").props.onClick());
  assert.deepEqual(plain(saved), [{ agent_assignment_mode: "selected_only", default_agent_binding_key: "ops" }]);
  const saving = create(createElement(WorkspaceAssignmentControlsPanel, { ...props, isSaving: true }));
  assert.equal(button(saving, "Saving…").props.disabled, true);
});

test("the roles panel shows the catalog, the create panel and the edit panel", () => {
  const calls = [];
  const record = (name) => (...args) => calls.push([name, ...args]);
  const { AdminRolesPanel } = loadStubbed("admin/components/usersTab/AdminRolesPanel.tsx",
    ["../AdminHeaderSlot", "./AdminIdentityRoleCatalog", "./AdminRoleEditPanel", "./IdentityCreatePanel"]);
  const role = { id: "r1", name: "ops" };
  const props = { roles: [role, { id: "r2", name: "dev" }], permissionCatalog: [], roleName: "new", roleDescription: "d", roleLoading: "create",
    roleError: "Taken", editingRole: role, showCreateRole: true, setRoleName: record("name"), setRoleDescription: record("description"),
    setShowCreateRole: record("show"), onCreateRole: record("create"), onLoadRoles() {}, onEditRole: record("edit"), onCloseEditPanel: record("close"),
    onDeleteRole: record("delete"), onUpdateRoleDescription: record("updateDescription"), onUpdateRolePermissions: record("updatePermissions") };
  const view = create(createElement(AdminRolesPanel, props));
  includesAll(text(view.root), ["+ New role", "Role catalog (2)", "Role name", "Lowercase letters, digits, hyphens and underscores.",
    "Description", "One line on what this role allows."]);
  assert.equal(text(view.root).includes("Taken"), false);
  const create_ = stubs(view, "IdentityCreatePanel")[0].props;
  assert.deepEqual([create_.title, create_.busy, create_.error, create_.testId], ["New role", true, "Taken", "role-create-panel"]);
  assert.equal(stubs(view, "AdminIdentityRoleCatalog")[0].props.roles.length, 2);
  assert.equal(hostCount(view), 17);
  act(() => button(view, "+ New role").props.onClick());
  act(() => all(view, "input")[0].props.onChange({ target: { value: "x" } }));
  act(() => all(view, "input")[1].props.onChange({ target: { value: "y" } }));
  act(() => create_.onClose());
  const edit = stubs(view, "AdminRoleEditPanel")[0].props;
  act(() => edit.onSaveDescription(role, "z"));
  act(() => edit.onSavePermissions(role, ["p"]));
  act(() => edit.onDelete(role));
  assert.deepEqual(plain(calls.map(([name, ...args]) => [name, args.length])), [["show", 1], ["name", 1], ["description", 1], ["show", 1],
    ["updateDescription", 2], ["updatePermissions", 2], ["delete", 1], ["close", 0]]);
  const closed = create(createElement(AdminRolesPanel, { ...props, showCreateRole: false, editingRole: null }));
  includesAll(text(closed.root), ["Taken"]);
  assert.equal(stubs(closed, "IdentityCreatePanel").length + stubs(closed, "AdminRoleEditPanel").length, 0);
});
