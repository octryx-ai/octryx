// Render guards for admin parts split into smaller functions: the Workspace settings section switch, a repository's
// coding setup record, and the user and group actions of the users tab keep the same
// structure and calls.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text, tick } from "./settingsRenderHarness.mjs";
import { all, create, createAsync, includesAll, noop, plain } from "./adminGuardRenderers.mjs";
import { loadStubbed, stubs } from "./adminGuardStubLoader.mjs";

const SECTIONS = ["/CodeRepositoriesSection", "/WorkspaceDataClassificationCard", "/WorkspaceModelsSection", "/WorkspaceCodingSection",
  "/WorkspaceRulesSection", "/WorkspaceDocumentationTargetCard", "/WorkspaceCorpIdentityCard", "/KnowledgeRepositoryPolicyPanel",
  "/AdminWorkspaceCompositionSection", "/ProjectAccessSection", "/WorkspaceRolesSection", "/PluginsPage", "/ProjectConnectorSettingsSection",
  "/ProjectKnowledgeLookupSection", "/ProjectObservabilitySection", "/ProjectPolicyGroup",
  "/ProjectQualityPoliciesSection", "/ProjectResourcesSection", "/WorkspaceRepositoriesSection", "/PrReviewBotSection", "/ProjectSettingsOverview",
  "/ProjectSkillsSection", "/ProjectVoiceSection", "/ProjectWorkflowProposalSection"];
const C = 'ctx={"c":1}';
const EXPECTED = {
  access: `ProjectAccessSection(${C})`,
  roles: "WorkspaceRolesSection(workspaceId=p1,workspaceName=Harbor)",
  plugins: 'PluginsPage(isPlatformAdmin=true,mode=workspace,workspace={"id":"p1","name":"Harbor"})',
  models: "WorkspaceModelsSection(projectId=p1)",
  coding: "WorkspaceCodingSection(isPlatformAdmin=true,onOpenModels=fn,projectId=p1)",
  connectors: `ProjectConnectorSettingsSection(${C})`,
  knowledge: `ProjectKnowledgeLookupSection(${C}) WorkspaceDocumentationTargetCard(isAdmin=true,projectId=p1) ProjectResourcesSection(${C},view=knowledge)`,
  repositories: `WorkspaceRepositoriesSection(workspaceId=p1) PrReviewBotSection(workspaceId=p1) KnowledgeRepositoryPolicyPanel(workspaceId=p1) `
    + `ProjectResourcesSection(${C},view=repositories) details(className=admin-modal__stack) summary(className=admin-panel__hint) `
    + 'CodeRepositoriesSection(props={"c":1}) ProjectPolicyGroup(purpose=Test, lint and SAST defaults, and how repositories are created.,'
    + `title=Code quality and repository bootstrap) ProjectQualityPoliciesSection(${C})`,
  agents: `AdminWorkspaceCompositionSection(${C},view=agents) ProjectSkillsSection(${C}) ProjectPolicyGroup(purpose=Whether a chat without a `
    + `selected workflow gets one workflow proposal.,title=Workflow proposals) ProjectWorkflowProposalSection(${C})`,
  rules: "WorkspaceRulesSection(onOpenSection=fn,projectId=p1,projectName=Harbor) WorkspaceDataClassificationCard(onOpenMatrix=fn,"
    + "policyHref=/chat?area=agents&workspace_id=p1&agents_view=policy,projectId=p1) WorkspaceCorpIdentityCard(isAdmin=true,projectId=p1)",
  "rules:classification": "WorkspaceDataClassificationCard(onOpenMatrix=fn,policyHref=/chat?area=agents&workspace_id=p1&agents_view=policy,"
    + "projectId=p1) WorkspaceRulesSection(onOpenSection=fn,projectId=p1,projectName=Harbor) WorkspaceCorpIdentityCard(isAdmin=true,projectId=p1)",
  observability: `ProjectObservabilitySection(${C})`,
  voice: `ProjectVoiceSection(${C})`,
  diagnostics: `AdminWorkspaceCompositionSection(${C},onOpenSection=fn,view=diagnostics)`,
  overview: 'ProjectSettingsOverview(onOpenSection=fn,project={"id":"p1","name":"Harbor"})',
};
const shown = (value) => (typeof value === "function" ? "fn" : value && typeof value === "object" ? JSON.stringify(value) : String(value));
const signature = (view) => view.root.findAll((node) => typeof node.type === "string").map((node) => {
  const props = Object.entries(node.props).filter(([key]) => key !== "children").sort(([a], [b]) => a.localeCompare(b));
  return `${node.type.replace("stub:", "")}(${props.map(([key, value]) => `${key}=${shown(value)}`).join(",")})`;
}).join(" ");

test("the Workspace settings section content renders the same sections, in order, with the same props", () => {
  const opened = [];
  const sections = [];
  const { ProjectSettingsSectionContent } = loadStubbed("admin/components/projectsTab/ProjectSettingsSectionContent.tsx", SECTIONS, {},
    { "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) } });
  for (const key of Object.keys(EXPECTED)) {
    const [section, focus = null] = key.split(":");
    const view = create(createElement(ProjectSettingsSectionContent, { ctx: { c: 1 }, project: { id: "p1", name: "Harbor" }, section,
      isAdmin: true, onOpenSection: (next) => sections.push(next), focus }));
    assert.equal(signature(view), EXPECTED[key], key);
    if (section === "rules") stubs(view, "WorkspaceDataClassificationCard")[0].props.onOpenMatrix();
    if (section === "coding") stubs(view, "WorkspaceCodingSection")[0].props.onOpenModels();
  }
  assert.deepEqual(opened, ["classificationPolicy", "classificationPolicy"]);
  assert.deepEqual(sections, ["models"]);
  const unknown = create(createElement(ProjectSettingsSectionContent, { ctx: {}, project: { id: "p1", name: "H" }, section: "nope", isAdmin: false, onOpenSection: noop }));
  assert.equal(stubs(unknown, "ProjectSettingsOverview").length, 1);
});

test("the repository coding setup record loads, edits and saves the setup", async () => {
  const saves = [];
  let refuse = null;
  const api = {
    loadCodingSetup: async () => ({ owners: ["ann", "bob"], pr_target_branch: "main", environment_file: "app/env.json" }),
    saveCodingSetup: async (...args) => { if (refuse) throw refuse; saves.push(args); },
    sourceText: (source) => `Knowledge source "${source.name}"`,
  };
  const { RepositoryCodingSetup } = loadStubbed("admin/components/projectsTab/repositories/RepositoryCodingSetup.tsx", [], {}, { "./workspaceRepositoriesApi": api });
  let savedCount = 0;
  const repository = { id: "r1", name: "shop", default_branch: "", source: { kind: "knowledge_source", name: "Shop" } };
  const view = await createAsync(createElement(RepositoryCodingSetup, { workspaceId: "w1", repository, onSaved: () => { savedCount += 1; }, onClose: noop }));
  includesAll(text(view.root), ["Repository · shop", "Close", "Source", "Knowledge source \"Shop\"", "Default branch", "–", "Branches", "Branch naming rule",
    "Placeholders: {type}", "Pull request target branch", "Protected branches", "Owners", "Default reviewers", "Coding setup", "Environment file",
    "Setup commands", "Coverage report paths", "One entry per line.", "Save coding setup"]);
  assert.equal(all(view, "textarea").length, 13);
  assert.equal(all(view, "input").length, 4);
  assert.equal(view.root.find((node) => node.props["aria-label"] === "Owners").props.value, "ann\nbob");
  assert.equal(byTestId(view, "repository-environment-file").length, 1);
  const env = () => view.root.find((node) => node.type === "input" && node.props["aria-label"] === "Environment file");
  act(() => env().props.onChange({ target: { value: "../x" } }));
  assert.equal(view.root.findAll((node) => node.props.role === "alert").length, 1);
  assert.equal(all(view, "button").find((node) => text(node) === "Save coding setup").props.disabled, true);
  act(() => env().props.onChange({ target: { value: "" } }));
  act(() => view.root.find((node) => node.props["aria-label"] === "Test commands").props.onChange({ target: { value: " npm test \n\n" } }));
  await act(async () => all(view, "button").find((node) => text(node) === "Save coding setup").props.onClick());
  await tick();
  const body = plain(saves[0][2]);
  assert.deepEqual([body.owners, body.test_commands, body.pr_target_branch, body.environment_file, body.builder_runtime_image], [["ann", "bob"], ["npm test"], "main", null, ""]);
  assert.equal(Object.keys(body).length, 17);
  assert.equal(savedCount, 1);
  assert.ok(text(view.root).includes("Saved the coding setup."));
  refuse = new Error("Nope");
  await act(async () => all(view, "button").find((node) => text(node) === "Save coding setup").props.onClick());
  await tick();
  assert.equal(view.root.findAll((node) => node.props.role === "alert" && text(node) === "Nope").length, 1);

  const failing = await createAsync(createElement(loadStubbed("admin/components/projectsTab/repositories/RepositoryCodingSetup.tsx", [], {},
    { "./workspaceRepositoriesApi": { ...api, loadCodingSetup: async () => { throw new Error("Gone"); } } }).RepositoryCodingSetup,
  { workspaceId: "w1", repository: { ...repository, default_branch: "main", source: { kind: "url", name: "git" } }, onSaved: noop, onClose: noop }));
  includesAll(text(failing.root), ["Loading the coding setup…", "Gone", "main", "git"]);
});

const recorder = () => {
  const log = [];
  const setter = (name) => (value) => log.push([name, typeof value === "function" ? value([{ id: "g1", name: "b" }]) : value]);
  return { log, setter };
};

test("the users tab user actions open, save, (de)activate and regroup a user", async () => {
  const { createAdminUserActions } = loadStubbed("admin/components/usersTab/adminUserActions.tsx", []);
  const { log, setter } = recorder();
  const asked = [];
  const deps = { readJson: async (url) => { log.push(["read", url]); return [{ id: "i1" }]; }, ask: (request) => asked.push(request),
    loadUserApiKeys: (user) => log.push(["keys", user.id]), loadGroups: async () => log.push(["groups"]),
    onRoleChange: async (...args) => log.push(["role", ...args]), onDeactivateUser: async (id) => log.push(["deactivate", id]),
    onUpdateUser: async (id, payload) => { log.push(["update", id, payload]); if (payload.group_ids === "fail") throw new Error("no"); return { id, updated: true }; },
    onResetUserPassword: async (...args) => log.push(["password", ...args]) };
  for (const name of ["setEditingUser", "setUserActionLoading", "setUserActionError", "setOidcIdentities", "setOidcIdentityLoading", "setOidcIdentityError"]) deps[name] = setter(name);
  const actions = createAdminUserActions(deps);
  assert.deepEqual(Object.keys(actions), ["openEditUser", "handleSaveProfile", "handleSaveRole", "handleResetPasswordDirect", "handleToggleUserStatus", "handleGroupChange"]);
  actions.openEditUser({ id: "u1", username: "ann" });
  await tick();
  assert.deepEqual(plain(log.splice(0)), [["setEditingUser", { id: "u1", username: "ann" }], ["setUserActionError", null], ["setOidcIdentities", []],
    ["setOidcIdentityError", null], ["keys", "u1"], ["setOidcIdentityLoading", true], ["read", "/admin/chat/api/panel/users/u1/oidc-identities"],
    ["setOidcIdentities", [{ id: "i1" }]], ["setOidcIdentityError", null], ["setOidcIdentityLoading", false]]);
  await actions.handleSaveProfile("u1", { username: "a" });
  await actions.handleSaveRole("u1", ["dev"]);
  await actions.handleResetPasswordDirect("u1", "pw");
  assert.deepEqual(plain(log.splice(0)), [["update", "u1", { username: "a" }], ["setEditingUser", { id: "u1", updated: true }], ["role", "u1", ["dev"]], ["password", "u1", "pw"]]);
  await actions.handleToggleUserStatus({ id: "u2", username: "bob", is_active: true });
  assert.equal(asked[0].title, "Deactivate bob?");
  assert.equal(asked[0].confirmLabel, "Deactivate bob");
  await asked[0].run();
  await actions.handleToggleUserStatus({ id: "u3", username: "cleo", is_active: false });
  await actions.handleGroupChange({ id: "u4" }, ["g1"]);
  await actions.handleGroupChange({ id: "u5" }, "fail");
  assert.deepEqual(plain(log.splice(0)), [["deactivate", "u2"], ["setUserActionError", null], ["setUserActionLoading", "status:u3"],
    ["update", "u3", { is_active: true }], ["setUserActionError", null], ["setUserActionLoading", null], ["setUserActionLoading", "groups:u4"],
    ["update", "u4", { group_ids: ["g1"] }], ["groups"], ["setUserActionError", null], ["setUserActionLoading", null], ["setUserActionLoading", "groups:u5"],
    ["update", "u5", { group_ids: "fail" }], ["setUserActionError", "no"], ["setUserActionLoading", null]]);
  const failing = createAdminUserActions({ ...deps, readJson: async () => { throw new Error("idp down"); } });
  failing.openEditUser({ id: "u9" });
  await tick();
  assert.deepEqual(log.filter(([name]) => name === "setOidcIdentityError").map(([, value]) => value), [null, "idp down"]);
});

test("the users tab group actions create, update, toggle and delete a group", async () => {
  const { createAdminGroupActions } = loadStubbed("admin/components/usersTab/adminGroupActions.ts", []);
  const { log, setter } = recorder();
  const asked = [];
  let fail = false;
  const deps = { readJson: async (url, init) => { log.push(["read", url, init.method, init.body ? JSON.parse(init.body) : null]); if (fail) throw new Error("bad");
    return { id: "g1", name: "a" }; }, ask: (request) => asked.push(request), groupName: "a", groupDescription: "d" };
  for (const name of ["setGroups", "setGroupName", "setGroupDescription", "setGroupLoading", "setGroupError", "setShowCreateGroup"]) deps[name] = setter(name);
  const actions = createAdminGroupActions(deps);
  assert.deepEqual(Object.keys(actions), ["handleCreateGroup", "handleUpdateGroup", "handleToggleGroup", "handleDeleteGroup"]);
  let prevented = 0;
  await actions.handleCreateGroup({ preventDefault: () => { prevented += 1; } });
  assert.equal(prevented, 1);
  assert.deepEqual(plain(log.splice(0)), [["setGroupLoading", "create"], ["read", "/admin/chat/api/panel/identity-groups", "POST", { name: "a", description: "d" }],
    ["setGroups", [{ id: "g1", name: "a" }, { id: "g1", name: "b" }]], ["setGroupName", ""], ["setGroupDescription", ""], ["setGroupError", null],
    ["setShowCreateGroup", false], ["setGroupLoading", null]]);
  await actions.handleUpdateGroup({ id: "g1" }, { rls_attributes: [] });
  await actions.handleUpdateGroup({ id: "g1" }, { description: "x" });
  await actions.handleToggleGroup({ id: "g1", is_active: true });
  assert.deepEqual(plain(log.splice(0)).filter(([name]) => name !== "setGroups"), [["setGroupLoading", "rls:g1"], ["read", "/admin/chat/api/panel/identity-groups/g1", "PUT", { rls_attributes: [] }],
    ["setGroupError", null], ["setGroupLoading", null], ["setGroupLoading", "update:g1"], ["read", "/admin/chat/api/panel/identity-groups/g1", "PUT", { description: "x" }],
    ["setGroupError", null], ["setGroupLoading", null], ["setGroupLoading", "toggle:g1"], ["read", "/admin/chat/api/panel/identity-groups/g1", "PUT", { is_active: false }],
    ["setGroupError", null], ["setGroupLoading", null]]);
  fail = true;
  await actions.handleCreateGroup({ preventDefault: noop });
  await actions.handleUpdateGroup({ id: "g1" }, {});
  await actions.handleToggleGroup({ id: "g1", is_active: false });
  assert.deepEqual(log.filter(([name]) => name === "setGroupError").map(([, value]) => value), ["bad", "bad", "bad"]);
  log.splice(0);
  fail = false;
  actions.handleDeleteGroup({ id: "g2", name: "Ops" });
  assert.deepEqual([asked[0].title, asked[0].confirmLabel, asked[0].done], ["Delete group Ops?", "Delete Ops", "Group Ops deleted."]);
  await asked[0].run();
  assert.deepEqual(plain(log), [["read", "/admin/chat/api/panel/identity-groups/g2", "DELETE", null], ["setGroups", [{ id: "g1", name: "b" }]], ["setGroupError", null]]);
});
