// Render guards for admin parts split into smaller functions: the skill merge conflict card, the groups panel, the SSO
// mapping card of one identity provider and the connection repository picker render the same structure and make the
// same calls.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, plain } from "./adminGuardRenderers.mjs";
import { loadStubbed, stubs } from "./adminGuardStubLoader.mjs";
import { button, hostCount } from "./adminGuardTreeReaders.mjs";

const conflict = { id: "c1", path: "SKILL.md", kind: "lines", base: ["a\n", "b\n"], ours: ["a\n", "B\n"], theirs: ["a\n", "c\n"],
  relocation: { path: "other.md", line: 3, end_line: 4, block: ["x\n"] } };
const report = { base_commit: "1234567890", theirs_commit: "abcdef1234", from_version: 2 };

test("the skill conflict card shows the three sides, the choices and the hand-edited merge", async () => {
  const { SkillConflictCard } = loadStubbed("admin/components/skillCatalog/SkillConflictCard.tsx", []);
  const resolved = [];
  const props = { conflict, report, resolution: undefined, editable: true, busy: false,
    onResolve: async (resolution) => { resolved.push(resolution); return true; } };
  const view = create(createElement(SkillConflictCard, props));
  includesAll(text(view.root), ["Conflict", "SKILL.md", "you and upstream changed the same lines", "Upstream before · 12345678", "Yours · v2",
    "Upstream now · abcdef12", "Upstream moved this block to other.md:3–4", "Apply my change in the new place", "Take upstream", "Keep mine",
    "Edit by hand"]);
  assert.equal(all(view, "div").filter((node) => node.props.className === "loc").length, 1);
  assert.equal(all(view, "div")[0].props["data-testid"], "skill-conflict-c1");
  assert.equal(hostCount(view), 36);
  await act(async () => byTestId(view, "skill-conflict-choice-relocate")[0].props.onClick());
  act(() => byTestId(view, "skill-conflict-choice-manual")[0].props.onClick());
  assert.equal(byTestId(view, "skill-conflict-manual")[0].props.value, "a\nB\n");
  act(() => byTestId(view, "skill-conflict-manual")[0].props.onChange({ target: { value: " " } }));
  await act(async () => byTestId(view, "skill-conflict-manual-save")[0].props.onClick());
  includesAll(text(view.root), ["Write the merged text first."]);
  act(() => byTestId(view, "skill-conflict-manual")[0].props.onChange({ target: { value: "merged" } }));
  await act(async () => byTestId(view, "skill-conflict-manual-save")[0].props.onClick());
  assert.deepEqual(plain(resolved), [{ choice: "relocate" }, { choice: "manual", text: "merged" }]);
  act(() => button(view, "Cancel").props.onClick());
  assert.equal(byTestId(view, "skill-conflict-manual").length, 0);
  const done = create(createElement(SkillConflictCard, { ...props, conflict: { ...conflict, relocation: null, kind: "file", base: [] },
    resolution: { choice: "mine" }, editable: false }));
  includesAll(text(done.root), ["Resolved", "Your lines kept", "(no lines)"]);
  assert.equal(byTestId(done, "skill-conflict-choice-relocate").length, 0);
  assert.equal(byTestId(done, "skill-conflict-choice-mine")[0].props.className, "policies__choice policies__choice--selected");
});

test("the groups panel opens the create panel, lists the groups and edits one", () => {
  const { AdminGroupsPanel } = loadStubbed("admin/components/usersTab/AdminGroupsPanel.tsx", ["/AdminHeaderSlot", "./AdminGroupEditPanel",
    "./AdminIdentityGroupCatalog", "./IdentityCreatePanel"]);
  const calls = [];
  const record = (name) => (...args) => calls.push([name, ...args]);
  const group = { id: "g1", name: "Ops" };
  const props = { groups: [group], groupName: "Ops", groupDescription: "D", groupError: "Taken", groupLoading: "create", editingGroup: group,
    showCreateGroup: true, setGroupName: record("name"), setGroupDescription: record("description"), setShowCreateGroup: record("show"),
    onCreateGroup: record("create"), onRefresh: record("refresh"), onEditGroup: record("edit"), onCloseEditPanel: record("close"),
    onUpdateGroup: record("update"), onToggleGroup: record("toggle"), onDeleteGroup: record("delete") };
  const view = create(createElement(AdminGroupsPanel, props));
  includesAll(text(view.root), ["+ New group", "Groups (1)", "Group name ", "*", "Description"]);
  const panel = stubs(view, "IdentityCreatePanel")[0].props;
  assert.deepEqual([panel.title, panel.busy, panel.error, panel.testId], ["New group", true, "Taken", "group-create-panel"]);
  assert.equal(stubs(view, "AdminIdentityGroupCatalog")[0].props.onCreateGroup, undefined);
  assert.equal(all(view, "div").filter((node) => node.props.className === "admin-panel__error").length, 0);
  assert.equal(hostCount(view), 15);
  act(() => all(view, "input")[0].props.onChange({ target: { value: "Dev" } }));
  act(() => all(view, "input")[1].props.onChange({ target: { value: "E" } }));
  act(() => panel.onClose());
  const edit = stubs(view, "AdminGroupEditPanel")[0].props;
  act(() => edit.onUpdateGroup(group, { description: "x" }));
  act(() => edit.onDeleteGroup(group));
  act(() => byTestId(view, "group-create-open")[0].props.onClick());
  assert.deepEqual(plain(calls.map((call) => call[0])), ["name", "description", "show", "update", "delete", "close", "show"]);
  const closed = create(createElement(AdminGroupsPanel, { ...props, showCreateGroup: false, editingGroup: null }));
  includesAll(text(closed.root), ["Taken"]);
  assert.equal(stubs(closed, "IdentityCreatePanel").length + stubs(closed, "AdminGroupEditPanel").length, 0);
  act(() => stubs(closed, "AdminIdentityGroupCatalog")[0].props.onCreateGroup());
  assert.deepEqual(calls.at(-1), ["show", true]);
});

test("the SSO mapping card of a provider saves the claims and tests them with the admin's sign-in", async () => {
  const calls = [];
  const provider = { id: "idp1", name: "Entra", groups_claim: "groups", roles_claim: "roles", known_groups: ["a"], known_roles: ["r1", "r2"] };
  const api = { listSsoProviders: async () => [provider],
    saveSsoMapping: async (...args) => { calls.push(args); return { ...provider, groups_claim: args[1], roles_claim: args[2] }; },
    loadMyClaims: async (id) => { calls.push(["claims", id]); return { groups: ["eng", "ops"], roles: [] }; } };
  const { SsoMappingCards } = loadStubbed("admin/components/workRoles/SsoMappingCard.tsx", ["./WorkRolesParts"], {}, { "./workRolesApi": api });
  const view = await createAsync(createElement(SsoMappingCards, { canEdit: true }));
  const card = stubs(view, "Card")[0];
  assert.deepEqual([card.props.title, card.props.testId], ["SSO mapping · Entra", "sso-mapping-idp1"]);
  includesAll(text(view.root), ["Claim with the SSO groups", "Claim with the SSO roles", "Known from sign-ins", "1 SSO group · 2 SSO roles"]);
  const action = (id) => all(create(stubs(view, "Card")[0].props.actions), "button").find((node) => node.props["data-testid"] === id);
  assert.deepEqual(buttons(create(card.props.actions)), ["Test with my sign-in", "Save claims"]);
  assert.equal(action("sso-save").props.disabled, true);
  assert.equal(hostCount(view), 15);
  act(() => all(view, "input")[0].props.onChange({ target: { value: " teams " } }));
  const save = action("sso-save");
  await act(async () => save.props.onClick());
  const check = action("sso-test");
  await act(async () => check.props.onClick());
  assert.deepEqual(plain(calls), [["idp1", "teams", "roles"], ["claims", "idp1"]]);
  includesAll(text(view.root), ["Saved. Each person's groups and roles", "Your last sign-in: eng, ops", "Your last sign-in carried no value here."]);
  assert.equal(all(view, "input")[0].props.value, "teams");
  const empty = await createAsync(createElement(loadStubbed("admin/components/workRoles/SsoMappingCard.tsx", ["./WorkRolesParts"], {},
    { "./workRolesApi": { ...api, listSsoProviders: async () => [] } }).SsoMappingCards, { canEdit: false }));
  includesAll(text(empty.root), ["No identity provider is set up."]);
});

test("the connection repository picker searches, pages and chooses a repository", async () => {
  const calls = [];
  const repository = (slug, patch = {}) => ({ project_key: "P", slug, name: slug, repository_url: `u/${slug}`, registered: null, ...patch });
  let answer = { repositories: [repository("api", { name: "API" }), repository("web", { registered: { access_mode: "read_only", connector_key: "k" } })],
    next_start: 25, is_last_page: false };
  const api = { REPOSITORY_PAGE_SIZE: 25, connectionRepositoriesApi: { repositories: async (...args) => { calls.push(args);
    if (answer instanceof Error) throw answer; return answer; } } };
  const now = { setTimeout: (fn) => { fn(); return 1; }, clearTimeout() {} };
  const load = () => loadStubbed("admin/components/workspaceKnowledge/ConnectionRepositoryPicker.tsx", ["./KnowledgeFormField",
    "./KnowledgeReasonNotice", "/StatusLabel"], now, { "./connectionRepositoriesApi": api }).ConnectionRepositoryPicker;
  const chosen = [];
  const Picker = load();
  const view = await createAsync(createElement(Picker, { workspaceId: "w1", connectionId: "c1", selected: repository("web"),
    onSelect: (item) => chosen.push(item.slug) }));
  includesAll(text(view.root), ["P/api", "API", "P/web", "Previous", "Next", "1–2"]);
  assert.equal(stubs(view, "StatusLabel")[0].props.label, "Read only");
  assert.deepEqual(all(view, "input").slice(1).map((node) => node.props.checked), [false, true]);
  assert.equal(hostCount(view), 18);
  act(() => all(view, "input")[1].props.onChange());
  assert.deepEqual(chosen, ["api"]);
  await act(async () => byTestId(view, "connection-repo-next")[0].props.onClick());
  await act(async () => byTestId(view, "connection-repo-search")[0].props.onChange({ target: { value: " zz " } }));
  await tick();
  assert.deepEqual(plain(calls.map((call) => call[2])), [{ q: "", start: 0, limit: 25 }, { q: "", start: 25, limit: 25 },
    { q: "zz", start: 0, limit: 25 }]);
  answer = { repositories: [], next_start: null, is_last_page: true };
  const empty = await createAsync(createElement(load(), { workspaceId: "w1", connectionId: "c1", selected: null, onSelect() {} }));
  includesAll(text(empty.root), ["This connection lists no repositories."]);
  assert.equal(byTestId(empty, "connection-repo-next")[0].props.disabled, true);
  answer = new Error("Gone");
  const failed = await createAsync(createElement(load(), { workspaceId: "w1", connectionId: "c1", selected: null, onSelect() {} }));
  assert.equal(text(byTestId(failed, "connection-repo-error")[0]), "Gone");
});
