// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/settingsIdentitySecurity.test.mjs
//
// Identity pages explain built-in roles and data access attributes in
// plain language, access diagnostics link blocked rows to their fix page, and content
// security shows the analyzer chain as steps with LLM thresholds tied to llm_risk.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BUILT_IN_ADMIN_PERMISSIONS_LABEL,
  accessFixForRow,
  dataAccessAttributesLabel,
  roleDescription,
  rolePermissionsLabel,
} from "../../src/admin/components/usersTab/identityPresentation.ts";
import {
  gatePayload,
  gateProblems,
  readCommandSafety,
  saveErrorText,
} from "../../src/admin/components/commandSafety/commandSafetyModel.ts";

test("the built-in admin role reads as full access instead of zero permissions", () => {
  assert.equal(rolePermissionsLabel({ name: "admin", permissions: [] }), BUILT_IN_ADMIN_PERMISSIONS_LABEL);
  assert.equal(rolePermissionsLabel({ name: "viewer", permissions: [{}, {}, {}] }), "3 permissions");
  assert.equal(rolePermissionsLabel({ name: "custom", permissions: [{}] }), "1 permission");
});

test("seeded default role descriptions are replaced, custom descriptions are kept", () => {
  assert.match(roleDescription({ name: "viewer", description: "Default viewer role", is_core: true }), /Signs in/);
  assert.match(roleDescription({ name: "admin", description: "", is_core: true }), /Full platform access/);
  assert.equal(roleDescription({ name: "viewer", description: "Read-only auditors", is_core: true }), "Read-only auditors");
  assert.equal(roleDescription({ name: "custom", description: "Default custom role", is_core: false }), "Default custom role");
});

test("data access attributes are listed as key = value", () => {
  assert.equal(dataAccessAttributesLabel([]), "None");
  assert.equal(
    dataAccessAttributesLabel([
      { key: "region", value: "eu" },
      { key: "team", value: "risk" },
    ]),
    "region = eu, team = risk",
  );
});

test("blocked access rows link to the page that can fix them", () => {
  assert.deepEqual(
    accessFixForRow({ user: { is_active: false }, effective: { can_use_chat: false, assigned_project_count: 3 } }),
    { label: "Open user accounts", tab: "users" },
  );
  assert.equal(
    accessFixForRow({ user: { is_active: true }, effective: { can_use_chat: true, assigned_project_count: 0 } })?.tab,
    "projects",
  );
  assert.equal(
    accessFixForRow({ user: { is_active: true }, effective: { can_use_chat: true, assigned_project_count: 2 } }),
    null,
  );
});

// Command safety is one payload; a score of 0 is a value.
test("command safety reads the gate and sends one payload with the checks as switches", () => {
  const view = readCommandSafety({
    checks: [{ key: "exec_policy", label: "Blocked command patterns", outcomes: ["block", "ask"], enabled: true },
      { key: "llm_risk", label: "AI risk review", outcomes: ["ask", "block"], enabled: false }],
    llm_risk: { timeout_seconds: 8, review_threshold: 0, deny_threshold: 0, review_model: "" },
    lists: { always_deny_patterns: ["mkfs"], commands: ["ls"], git: ["log"], kubectl: ["get"], operators: ["&&"] },
    guard_rules: [{ id: "g1", label: "Guard", enabled: true }, { id: "g2", label: "Locked", enabled: true, locked: true }],
    workspaces: [{ id: "w", name: "W", mode: "override", differences: ["Block from score 60"] }],
  });
  assert.equal(view.llm.review_threshold, 0, "0 stays 0");
  assert.deepEqual(gateProblems(view), []);
  const payload = gatePayload(view, view.guardRules, view.customGuardRules);
  assert.deepEqual(payload.checks, { exec_policy: true, llm_risk: false });
  assert.deepEqual(payload.llm_risk, { timeout_seconds: 8, review_threshold: 0, deny_threshold: 0 });
  assert.deepEqual(payload.guard_rules, { g1: true }, "locked rules are not sent");
  assert.deepEqual(gateProblems({ ...view, checks: view.checks.map((check) => ({ ...check, enabled: false })) }), ["Keep at least one check on."]);
  assert.deepEqual(gateProblems({ ...view, llm: { ...view.llm, review_threshold: 70, deny_threshold: 60 } }),
    ["“Block from score” cannot be below “Ask a person from score”."]);
  assert.equal(saveErrorText({ status: 422, code: "command_safety_no_check" }), "Not saved: keep at least one check on.");
  assert.equal(view.workspaces[0].mode, "override");
});

// Sign-in & SSO maps external groups to local roles and groups picked by name.
test("group mappings round-trip as rows; incomplete rows are reported and never saved", async () => {
  const { mappingProblems, mappingRecord, mappingRows } = await import("../../src/admin/components/usersTab/identityMappingRows.ts");
  const rows = mappingRows({ "ext-a": ["admin"], "ext-b": ["viewer", "operator"] });
  assert.deepEqual(rows, [{ external: "ext-a", targets: ["admin"] }, { external: "ext-b", targets: ["viewer", "operator"] }]);
  assert.deepEqual(mappingRecord([...rows, { external: " ext-a ", targets: ["viewer"] }, { external: "", targets: ["x"] },
    { external: "ext-c", targets: [] }]), { "ext-a": ["admin", "viewer"], "ext-b": ["viewer", "operator"] });
  assert.deepEqual(mappingProblems([{ external: "", targets: ["x"] }, { external: "ext-c", targets: [] }, { external: "", targets: [] }]),
    ["Row 1: enter the external group name.", "Row 2: pick at least one local entry."]);
  assert.deepEqual(mappingRows(null), []);
});
