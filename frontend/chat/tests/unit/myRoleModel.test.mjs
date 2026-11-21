// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/myRoleModel.test.mjs
//
// Roles in the chat and on the phone (roles contract §3.3/§4/§5): the banner and notice the chat shows
// above the composer, the calm line of a role refusal, and the phone's read-only words.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  EMPTY_REASON_EN,
  functionName,
  membersWithoutRoleText,
  readEffectivePermission,
  readRoleRefusal,
  readWorkspaceRoles,
  roleChatNotice,
  roleHeaderText,
  roleRefusalText,
  viaSummary,
  writeConnectionsText,
} from "../../src/chat/roles/myRoleModel.ts";
import { foldToolSteps } from "../../src/chat/toolStepFoldModel.ts";

const me = (overrides = {}) => ({
  workspace_id: "w1",
  user_id: "u1",
  enforced: true,
  platform_admin: false,
  roles: [],
  functions: [],
  write_connections: "all",
  trusted: false,
  empty_reason: null,
  ...overrides,
});
const developer = { id: "r1", key: "engineer", name: "Developer", trusted: false, via: [{ kind: "sso_group", value: "eng-developers" }, { kind: "user" }] };
const releaseManager = { id: "r9", key: "release_manager", name: "Release manager", trusted: true, via: [{ kind: "user" }] };

test("switch on and no role: the API's empty reason, the Workspace named, who can assign roles", () => {
  const reason = "Du hast in diesem Workspace keine Rolle.";
  const notice = roleChatNotice(readEffectivePermission(me({ empty_reason: reason })), "Demo Shop");
  assert.equal(notice.kind, "empty");
  assert.equal(notice.text, reason);
  assert.equal(notice.workspace, "Demo Shop");
  assert.match(notice.hint, /Workspace admin of Demo Shop/);
  const fallback = roleChatNotice(readEffectivePermission(me()), "Demo Shop");
  assert.equal(fallback.text, EMPTY_REASON_EN);
});

test("nothing to say when the switch is off, a role applies, or the caller is a platform admin", () => {
  assert.equal(roleChatNotice(readEffectivePermission(me({ enforced: false })), "W"), null);
  assert.equal(roleChatNotice(readEffectivePermission(me({ roles: [developer] })), "W"), null);
  assert.equal(roleChatNotice(readEffectivePermission(me({ platform_admin: true })), "W"), null);
  assert.equal(roleChatNotice(null, "W"), null);
});

test("a trusted role gives the persistent notice naming the role", () => {
  const notice = roleChatNotice(readEffectivePermission(me({ roles: [developer, releaseManager], trusted: true })), "W");
  assert.deepEqual(notice, {
    kind: "trusted",
    text: "Trusted role (Release manager): your chat writes run without a plan confirmation.",
    roles: "Release manager",
  });
});

test("the header names the roles only while they apply", () => {
  assert.equal(roleHeaderText(readEffectivePermission(me({ roles: [developer] }))), "Your role: Developer");
  assert.equal(roleHeaderText(readEffectivePermission(me({ roles: [developer, releaseManager] }))), "Your roles: Developer, Release manager");
  assert.equal(roleHeaderText(readEffectivePermission(me({ enforced: false, roles: [developer] }))), "");
});

test("functions, how a role reaches the person and the write connections read as words", () => {
  assert.equal(functionName("decide_as_po"), "Decide as product owner");
  assert.equal(functionName("release_signoff"), "Release signoff");
  const permission = readEffectivePermission(me({ roles: [developer], write_connections: ["c1", "c2"] }));
  assert.equal(viaSummary(permission.roles[0]), "Through the SSO group eng-developers · Assigned to you");
  assert.equal(writeConnectionsText(permission), "2 named connections");
  assert.equal(writeConnectionsText(readEffectivePermission(me())), "Every connection of the Workspace");
});

test("a role refusal is read from the structured code only, never from prose", () => {
  const detail = {
    code: "role_tool_not_granted",
    message: "Your roles (Developer) do not include create_jira_ticket.",
    setting: "a role with a function whose tool set contains create_jira_ticket",
    who_can_change: "Workspace admin",
  };
  for (const result of [detail, { detail }, { error: detail }, JSON.stringify({ detail })]) {
    assert.equal(readRoleRefusal(result).code, "role_tool_not_granted");
  }
  assert.equal(
    roleRefusalText(readRoleRefusal({ detail })),
    "Your roles (Developer) do not include create_jira_ticket. Setting: a role with a function whose tool set contains create_jira_ticket. Who can change it: Workspace admin.",
  );
  assert.equal(readRoleRefusal("role_tool_not_granted: not allowed"), null);
  assert.equal(readRoleRefusal({ code: "something_else", message: "x" }), null);
  assert.equal(readRoleRefusal({ code: "po_function_required" }).message, "This decision needs the function Decide as product owner.");
});

test("a refused tool step is one calm line in the fold, not a failure", () => {
  const fold = foldToolSteps([
    {
      id: "t1",
      toolName: "create_jira_ticket",
      parameters: {},
      status: "error",
      createdAt: null,
      result: { detail: { code: "role_connection_not_granted", message: "Your roles may not write through Jira Cloud.", who_can_change: "Workspace admin" } },
    },
  ]);
  assert.deepEqual(fold.failures, [
    { id: "t1", blocked: true, text: "Your roles may not write through Jira Cloud. Who can change it: Workspace admin." },
  ]);
});

test("the admin view: switch state, members without a role and active assignments with their role", () => {
  const roles = readWorkspaceRoles({
    settings: { role_based_tools: false, version: 1 },
    roles: [{ id: "r1", name: "Developer" }, { id: "r9", name: "Release manager", trusted: true }],
    assignments: [
      { id: "a1", role_id: "r1", role_name: "Developer", subject: { kind: "sso_group", value: "eng-developers", label: "eng-developers" }, members: 14, is_active: true },
      { id: "a2", role_id: "r9", subject: { kind: "user", user_id: "u2", label: "Anna Keller" }, members: 1, is_active: true },
    ],
    members_without_role: [{ user_id: "u3", label: "Ben Roth" }, { user_id: "u4", label: "Cara Meier" }],
    can_edit: true,
  });
  assert.equal(roles.roleBasedTools, false);
  assert.equal(roles.assignments[1].roleName, "Release manager");
  assert.ok(roles.trustedRoleIds.has("r9"));
  assert.equal(membersWithoutRoleText(roles.membersWithoutRole, false), "These 2 members will have no tools: Ben Roth, Cara Meier");
  assert.equal(membersWithoutRoleText(["Ben Roth"], true), "This member has no tools: Ben Roth");
});
