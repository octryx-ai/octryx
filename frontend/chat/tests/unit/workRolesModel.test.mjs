// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workRolesModel.test.mjs
// Work roles (board 8): the presentation model of Admin › Roles & functions and Workspace › Roles.
import assert from "node:assert/strict";
import { test } from "node:test";

import { assignmentRows, auditChanges, auditSentence, CONFLICT_TEXT, errorView, extraEntries, matrixRows, membersText, membersWithoutRoleText, roleBadges, subjectKindLabel, TRUSTED_BADGE, unknownEntriesText, viaText } from "../../src/admin/components/workRoles/workRolesModel.ts";
import { roleDraft, roleDraftProblems, roleWriteBody, slugify } from "../../src/admin/components/workRoles/workRoleDraft.ts";

const fn = (key, name) => ({ id: key, key, name, description: "", workspace_id: null, built_in: true, tools: [], tools_version: 1, version: 1, role_keys: [] });
const role = (over) => ({
  id: "r1", key: "engineer", name: "Developer", description: "", workspace_id: null, built_in: true, is_active: true,
  function_keys: ["read"], delivery_connections: "all", connection_ids: [], trusted: false, trusted_changed_by: null,
  trusted_changed_at: null, command_policy: { allow: [], deny: [] }, version: 3, assignment_count: 0, ...over,
});

test("a trusted role carries the attention badge with the contract's wording; inactive and origin stay neutral", () => {
  assert.deepEqual(roleBadges(role({})).map((b) => [b.label, b.tone]), [["Built-in", "neutral"]]);
  const badges = roleBadges(role({ built_in: false, trusted: true, is_active: false }));
  assert.deepEqual(badges.map((b) => [b.label, b.tone]), [["Custom", "neutral"], [TRUSTED_BADGE, "attention"], ["Inactive", "neutral"]]);
  assert.equal(TRUSTED_BADGE, "Trusted · no plan confirmation");
});

test("matrix: one cell per function in the functions' order; active built-in first, inactive last and muted", () => {
  const functions = [fn("read", "Chat & knowledge"), fn("decide_as_po", "Decide as product owner")];
  const rows = matrixRows([
    role({ id: "old", name: "Old", built_in: false, is_active: false }),
    role({ id: "rm", name: "Release manager", built_in: false, function_keys: ["decide_as_po"] }),
    role({ id: "dev", name: "Developer", function_keys: ["read"] }),
  ], functions);
  assert.deepEqual(rows.map((r) => r.role.id), ["dev", "rm", "old"]);
  assert.deepEqual(rows[1].cells, [false, true]);
  assert.deepEqual(rows.map((r) => r.muted), [false, false, true]);
});

test("members without a role: the switch line and its confirmation name them, shortened after five", () => {
  assert.equal(membersWithoutRoleText([]), "Every member has a role.");
  assert.equal(membersWithoutRoleText([{ user_id: "1", label: "Marco" }]), "This member will have no tools: Marco.");
  const many = ["A", "B", "C", "D", "E", "F", "G"].map((label, i) => ({ user_id: String(i), label }));
  assert.equal(membersWithoutRoleText(many), "These 7 members will have no tools: A, B, C, D, E and 2 more.");
  assert.equal(membersWithoutRoleText(many.slice(0, 2), true), "These 2 members have no tools: A, B.");
});

test("errors: the API's message with setting and who can change it verbatim; a version conflict says it reloaded", () => {
  const refusal = Object.assign(new Error("Developer is still assigned 3 times."), {
    status: 409, code: "role_in_use",
    detail: { code: "role_in_use", message: "Developer is still assigned 3 times.", setting: "Assignments of Developer", who_can_change: "Workspace admin" },
  });
  assert.deepEqual(errorView(refusal), {
    message: "Developer is still assigned 3 times.", setting: "Assignments of Developer", whoCanChange: "Workspace admin", conflict: false,
  });
  const conflict = Object.assign(new Error("stale"), { status: 409, code: "version_conflict", detail: { code: "version_conflict", message: "stale" } });
  assert.deepEqual(errorView(conflict), { message: CONFLICT_TEXT, setting: null, whoCanChange: null, conflict: true });
  assert.equal(errorView(new Error(""), "Could not save.").message, "Could not save.");
});

test("assignments: active ones grouped per subject, SSO first, members from sign-in for SSO subjects", () => {
  const a = (id, subject, members, is_active = true) => ({ id, workspace_id: "w", role_id: id, role_key: id, role_name: id, subject, members, is_active, version: 1 });
  const rows = assignmentRows([
    a("po", { kind: "user", user_id: "u1", label: "Anna" }, 1),
    a("dev", { kind: "user", user_id: "u1", label: "Anna" }, 1),
    a("gone", { kind: "user", user_id: "u2", label: "Ben" }, 1, false),
    a("devs", { kind: "sso_group", value: "eng-developers", provider_id: null, label: "eng-developers" }, 14),
  ]);
  assert.deepEqual(rows.map((r) => [r.subject.label, r.assignments.map((x) => x.id)]), [["eng-developers", ["devs"]], ["Anna", ["po", "dev"]]]);
  assert.equal(membersText(rows[0].subject, 14), "14 people · from sign-in");
  assert.equal(membersText(rows[1].subject, 1), "1 person");
  assert.equal(subjectKindLabel({ kind: "sso_role" }, "Company Entra ID"), "SSO role · Company Entra ID");
  assert.equal(subjectKindLabel({ kind: "group" }), "Workspace group");
  assert.equal(viaText({ kind: "sso_group", value: "octryx-risk-po" }), "via SSO group octryx-risk-po");
  assert.equal(viaText({ kind: "user" }), "directly");
});

test("role editor: key from the name on create, problems block Save, PATCH sends only changes with expected_version", () => {
  assert.equal(slugify("Release Manager (Nacht)"), "release_manager_nacht");
  assert.equal(slugify("2nd line"), "r_2nd_line");
  const fresh = roleDraft(null);
  assert.deepEqual(roleDraftProblems(fresh, true), ["Enter a name.", "The key starts with a letter and uses a–z, 0–9 and _ (2–40 characters)."]);
  assert.deepEqual(roleDraftProblems({ ...fresh, name: "X", key: "x_1", delivery_connections: "selected" }, true),
    ["Pick at least one connection, or allow all."]);
  const existing = role({ command_policy: { allow: ["make test"], deny: [] } });
  const draft = { ...roleDraft(existing), deny: "terraform *\n\n  rm -rf *  ", is_active: false };
  assert.deepEqual(roleWriteBody(draft, existing), {
    command_policy: { allow: ["make test"], deny: ["terraform *", "rm -rf *"] }, is_active: false, expected_version: 3,
  });
  const created = roleWriteBody({ ...fresh, name: " Release manager ", key: "release_manager" }, null);
  assert.equal(created.key, "release_manager");
  assert.equal(created.name, "Release manager");
  assert.equal("expected_version" in created, false);
});

test("tool sets: user-added entries are told apart from the catalog; unknown entries get one notice", () => {
  const catalog = {
    groups: [{ connector: "jira", label: "Jira", risks: { read: [{ name: "get_jira_ticket", description: "", in_set: true }] } }],
    selectors: [{ entry: "risk:read", label: "Every read tool" }],
    unknown_entries: ["release_*"],
  };
  assert.deepEqual(extraEntries(["get_jira_ticket", "risk:read", "jira_*", "release_*"], catalog), ["jira_*", "release_*"]);
  assert.equal(unknownEntriesText([]), null);
  assert.equal(unknownEntriesText(["release_*"]), "1 entry matches no tool today: release_*. It is kept, because a tool may arrive later.");
});

test("audit: the action in words and before → after per changed field, functions by name", () => {
  assert.equal(auditSentence({ action: "role.trusted_changed", target_label: "Product owner", after: { trusted: true } }),
    "turned Trusted on for Product owner");
  assert.equal(auditSentence({ action: "settings.role_based_tools_changed", target_label: "Risk Team", after: { role_based_tools: false } }),
    "turned Role-based tools off in Risk Team");
  assert.equal(auditSentence({ action: "role.updated", target_label: "Contractor", after: { is_active: false } }), "deactivated the role Contractor");
  const functions = [fn("read", "Chat & knowledge"), fn("decide_as_po", "Decide as product owner")];
  assert.deepEqual(auditChanges({ before: { trusted: false, function_keys: ["read"] }, after: { trusted: true, function_keys: ["read", "decide_as_po"] } }, functions),
    ["Trusted: off → on", "Functions: Chat & knowledge → Chat & knowledge, Decide as product owner"]);
  assert.deepEqual(auditChanges({ before: null, after: { name: "Release manager" } }), ["Name: Release manager"]);
});

test("the matrix reads from 'may chat' to 'may change everything', whatever order the server lists", async () => {
  const { matrixRows, orderFunctions } = await import("../../src/admin/components/workRoles/workRolesModel.ts");
  const fns = ["approve_tools", "assign_roles", "custom_x", "read", "delivery"].map((key) => ({ key, name: key === "custom_x" ? "Audit export" : key }));
  assert.deepEqual(orderFunctions(fns).map((fn) => fn.key), ["read", "delivery", "approve_tools", "assign_roles", "custom_x"]);
  const role = (key, extra = {}) => ({ key, name: key, built_in: true, is_active: true, function_keys: ["read"], ...extra });
  const rows = matrixRows([role("agile_lead"), role("viewer"), role("workspace_admin"), role("release", { built_in: false })], fns);
  assert.deepEqual(rows.map((row) => row.role.key), ["workspace_admin", "agile_lead", "viewer", "release"]);
  assert.deepEqual(rows[0].cells, [true, false, false, false, false], "cells follow the ordered columns");
});
