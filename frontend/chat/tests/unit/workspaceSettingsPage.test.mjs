// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceSettingsPage.test.mjs
//
// The Workspace page's sections (old ids alias to their new home), the first editors for the
// command & file rules, MCP servers and budget overrides, and the Rules table.
import assert from "node:assert/strict";
import { test } from "node:test";

import { act, byTestId, click, render, server, text, tick } from "./settingsRenderHarness.mjs";
import {
  PROJECT_SETTINGS_GROUPS,
  PROJECT_SETTINGS_SECTIONS,
  projectSettingsGroupOf,
  resolveProjectSettingsTab,
} from "../../src/admin/components/projectsTab/projectSettingsSections.ts";
import {
  budgetAmount,
  readCoding,
  ruleDraftProblems,
  ruleFromDraft,
  ruleTarget,
} from "../../src/admin/components/workspaceSettings/workspaceSettingsModel.ts";

const CODING = () => ({
  requires_governed_routing: false,
  tool_rules: [
    { id: "no-push-to-main", kind: "command_prefix_denied", prefix: ["git", "push", "origin", "main"] },
    { id: "no-env-files", kind: "path_denied", tools: ["Read"], glob: "**/.env" },
  ],
  client_deny: [],
  client_ask: [],
});

test("the Workspace page has the mock's sections; a card address opens its section", () => {
  assert.deepEqual(PROJECT_SETTINGS_SECTIONS.map((section) => section.label), [
    "Overview", "Access", "Roles", "Plugins", "Models", "Coding tools & devices", "Connectors", "Knowledge", "Repositories",
    "Agents & skills", "Rules", "Observability", "Voice", "Diagnostics",
  ]);
  assert.equal(resolveProjectSettingsTab("documentation"), "knowledge");
  assert.equal(resolveProjectSettingsTab("classification"), "rules");
  for (const retired of ["runtimes", "policies", "capabilities", "design", "nope"]) {
    assert.equal(resolveProjectSettingsTab(retired), null, retired);
  }
});

test("the sections sit in five groups, each section in exactly one, so two short rows fit at 1280", () => {
  assert.deepEqual(PROJECT_SETTINGS_GROUPS.map((group) => group.label), ["Overview", "Access", "Models & agents", "Data", "Rules & monitoring"]);
  const grouped = PROJECT_SETTINGS_GROUPS.flatMap((group) => group.sections);
  assert.deepEqual([...grouped].sort(), PROJECT_SETTINGS_SECTIONS.map((section) => section.key).sort(), "every section once");
  assert.ok(PROJECT_SETTINGS_GROUPS.every((group) => group.sections.length <= 4), "a short second row");
  assert.equal(projectSettingsGroupOf("voice").key, "ai");
  assert.equal(projectSettingsGroupOf("diagnostics").key, "general");
  assert.equal(projectSettingsGroupOf("plugins").key, "access", "Plugins (phase 1) sit next to Access and Roles");
});

test("command & file rules: one typed row per kind, only the fields it needs, a free id", () => {
  assert.deepEqual(ruleDraftProblems({ kind: "command_argument_denied", command: "git push", argument: "", glob: "" }),
    ["Enter one argument without spaces."]);
  const rule = ruleFromDraft({ kind: "command_prefix_denied", command: " terraform  destroy ", argument: "", glob: "" }, ["command-terraform-destroy"]);
  assert.deepEqual(rule, { id: "command-terraform-destroy-2", kind: "command_prefix_denied", prefix: ["terraform", "destroy"] });
  const path = ruleFromDraft({ kind: "path_denied", command: "", argument: "", glob: "~/.ssh/**" }, []);
  assert.deepEqual(path.tools, ["Read", "Edit", "Write", "MultiEdit"]);
  assert.equal(ruleTarget(path), "~/.ssh/**");
  assert.equal(readCoding({ tool_rules: [] }), null, "an answer without the routing flag is not a policy");
});

test("budget inputs: empty inherits, anything else is an amount of 0 or more", () => {
  assert.equal(budgetAmount(""), null);
  assert.equal(budgetAmount("0"), 0);
  assert.equal(budgetAmount("12.5"), 12.5);
  assert.equal(budgetAmount("-1"), "invalid");
  assert.equal(budgetAmount("ten"), "invalid");
});

test("rendered Coding tools & devices: add a rule, remove one, block a permission, save the whole section", async () => {
  const srv = server((call) => {
    if (call.url.endsWith("/coding")) return { status: 200, body: call.method === "PUT" ? { ...CODING(), ...call.body } : CODING() };
    return { status: 404, body: {} };
  });
  const view = await render("admin/components/workspaceSettings/WorkspaceCodingSection.tsx", "WorkspaceCodingSection", srv,
    { projectId: "w1", isPlatformAdmin: false, onOpenModels: () => {} });
  try {
    assert.match(text(byTestId(view, "coding-rules")[0]), /no-push-to-main.*Command blocked.*git push origin main/);
    await click(view, "coding-add-rule");
    await act(async () => { byTestId(view, "coding-rule-command")[0].props.onChange({ target: { value: "terraform destroy" } }); });
    await click(view, "coding-rule-add");
    await act(async () => { view.root.findAll((node) => node.props["aria-label"] === "Remove no-env-files")[0].props.onClick(); });
    await act(async () => { byTestId(view, "coding-client-deny-input")[0].props.onChange({ target: { value: "Bash(rm -rf:*)" } }); });
    await click(view, "coding-client-deny-add");
    await act(async () => { byTestId(view, "coding-governed-routing")[0].props.onClick(); });
    await click(view, "coding-save");
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.deepEqual(put.body.tool_rules.map((rule) => rule.id), ["no-push-to-main", "command-terraform-destroy"]);
    assert.deepEqual(put.body.client_deny, ["Bash(rm -rf:*)"]);
    assert.equal(put.body.requires_governed_routing, true);
  } finally {
    act(() => view.unmount());
  }
});

test("rendered Rules: each row names where it is declared; budget saves empty as inherit; approvals open the drawer", async () => {
  const srv = server((call) => {
    if (call.url.includes("/tool-approvals")) {
      return { status: 200, body: { default: { require_for_risks: ["high"], require_for_tools: [], exempt_tools: [] }, risks: ["high"], tools: [],
        workspaces: [{ id: "w1", name: "Northwind", mode: "add", own: { require_for_risks: [], require_for_tools: ["send_email"], exempt_tools: [] }, effective: {} }],
        mcp: { servers: [], workspaces: [] } } };
    }
    if (call.url.endsWith("/budget")) {
      return { status: 200, body: call.method === "PUT" ? call.body : { session_usd: 100, request_usd: null, per_person_daily_usd: null,
        platform: { session_usd: 10, request_usd: 0, per_person_daily_usd: 50 } } };
    }
    if (call.url.endsWith("/coding")) return { status: 200, body: CODING() };
    if (call.url.endsWith("/mcp-servers")) {
      // Runtime's Workspace allow answer: the server in server_name, the Workspace in name.
      return { status: 200, body: { servers: [{ server_id: "s1", server_name: "docs-search", name: "Northwind", allowed: true }] } };
    }
    if (call.url.endsWith("/tools")) {
      return { status: 200, body: { source: "runtime_policy.tool_policy", policy: { allowlist: [], denylist: ["shell_exec"], allow_patterns: [],
        deny_patterns: [], allow_read_only: false } } };
    }
    return { status: 403, body: {} };
  });
  const view = await render("admin/components/workspaceSettings/WorkspaceRulesSection.tsx", "WorkspaceRulesSection", srv,
    { projectId: "w1", projectName: "Northwind", onOpenSection: () => {} });
  try {
    await tick();
    const page = text(view.root);
    assert.match(page, /Tool approvals.*Default \+ Send email.*Tool & approval policies/);
    assert.match(page, /MCP servers.*docs-search.*Connectors \(this Workspace\)/);
    assert.match(page, /Command safety.*Platform admins only/, "a page the caller may not read only links");
    assert.match(page, /Forbidden actions.*2 command & file rules/);
    assert.match(page, /Tools \(visibility\)hidden: shell_execWorkspace tool policy \(runtime copy\) · read-only/, "review finding 4");
    assert.equal(text(byTestId(view, "budget-platform")[0]), "Platform value: $10 per session · no cap per request · $50 per person/day");
    assert.equal(byTestId(view, "budget-session_usd")[0].props.value, "100");
    assert.equal(byTestId(view, "budget-request_usd")[0].props.placeholder, undefined, "no example value");
    await act(async () => { byTestId(view, "budget-session_usd")[0].props.onChange({ target: { value: "" } }); });
    await act(async () => { byTestId(view, "budget-per_person_daily_usd")[0].props.onChange({ target: { value: "25" } }); });
    await click(view, "budget-save");
    await tick();
    assert.deepEqual(srv.calls.find((call) => call.method === "PUT").body, { session_usd: null, request_usd: null, per_person_daily_usd: 25 });
    await click(view, "rules-approvals-edit");
    assert.match(text(view.root), /Tool approvals/);
  } finally {
    act(() => view.unmount());
  }
});

test("chat Agents → Policy shows device runs read-only with Edit in Settings", async () => {
  const srv = server(() => ({ status: 200, body: { project_id: "w1", enabled: true, can_edit: true, platform_enabled: true } }));
  let opened = 0;
  const view = await render("chat/devices/DeviceRunsPolicyCard.tsx", "DeviceRunsPolicyCard", srv,
    { projectId: "w1", isPlatformAdmin: true, readOnly: true, onEditInSettings: () => { opened += 1; } });
  try {
    const switches = view.root.findAll((node) => node.props.role === "switch");
    assert.ok(switches.length > 0 && switches.every((node) => node.props["aria-disabled"] === true));
    assert.ok(!switches.some((node) => node.props["aria-label"] === "Device runs on this platform"), "no platform switch here");
    await click(view, "device-runs-edit-in-settings");
    assert.equal(opened, 1);
  } finally {
    act(() => view.unmount());
  }
});

test("Roles marks permissions no check reads as Not enforced yet and saves only resource and action", async () => {
  const saved = [];
  const view = await render("admin/components/usersTab/AdminRoleEditPanel.tsx", "AdminRoleEditPanel", server(() => ({ status: 200, body: {} })), {
    role: { id: "r1", name: "analyst", description: "", is_core: false, user_count: 0, permissions: [], assigned_users: [] },
    permissionCatalog: [{ resource: "auth", action: "login", enforced: true }, { resource: "tools", action: "execute", enforced: false }],
    roleLoading: null, onClose: () => {}, onSaveDescription: () => {}, onDelete: () => {},
    onSavePermissions: (_role, permissions) => saved.push(permissions),
  });
  try {
    const page = text(view.root);
    assert.match(page, /1 of 2 permissions/);
    assert.match(page, /executeNot enforced yet/);
    assert.doesNotMatch(page, /loginNot enforced yet/);
    const box = view.root.findAll((node) => node.type === "input" && node.props.type === "checkbox")[1];
    await act(async () => { box.props.onChange({ target: { checked: true } }); });
    assert.equal(JSON.stringify(saved[0]), JSON.stringify([{ resource: "tools", action: "execute" }]));
  } finally {
    act(() => view.unmount());
  }
});

test("the Workspace approval drawer can only add: no exemption picker, no exemptions saved (review finding 8)", async () => {
  const saved = [];
  const props = (workspace) => ({
    title: "Northwind", workspace, mode: "add", policy: { require_for_risks: [], require_for_tools: [], exempt_tools: ["send_email"] },
    defaults: { require_for_risks: ["high"], require_for_tools: [], exempt_tools: [] }, risks: ["high"], tools: [], busy: false,
    problem: null, onClose: () => {}, onSave: (mode, policy) => saved.push(JSON.parse(JSON.stringify(policy))),
  });
  const view = await render("admin/components/toolApprovals/ApprovalPolicyDrawer.tsx", "ApprovalPolicyDrawer", server(() => ({ status: 200, body: {} })), props(true));
  try {
    assert.equal(byTestId(view, "approval-never").length, 0);
    await click(view, "approval-save");
    assert.deepEqual(saved[0].exempt_tools, []);
  } finally {
    act(() => view.unmount());
  }
  const platform = await render("admin/components/toolApprovals/ApprovalPolicyDrawer.tsx", "ApprovalPolicyDrawer", server(() => ({ status: 200, body: {} })), props(false));
  try {
    assert.ok(byTestId(platform, "approval-never").length > 0, "the platform default keeps its exemptions");
  } finally {
    act(() => platform.unmount());
  }
});

test("session permissions by role are read safely and sent with the coding policy", async () => {
  const { readCoding, codingPayload, DEFAULT_ROLE_MODES } = await import(
    "../../src/admin/components/workspaceSettings/workspaceSettingsModel.ts");
  const coding = readCoding({ requires_governed_routing: false, tool_rules: [], client_deny: [],
    role_modes: { member: "bypass", viewer: "root" } });
  assert.deepEqual(coding.roleModes, { ...DEFAULT_ROLE_MODES, member: "bypass" });
  assert.deepEqual(readCoding({ requires_governed_routing: false, tool_rules: [] }).roleModes, DEFAULT_ROLE_MODES);
  assert.deepEqual(codingPayload(coding).role_modes, coding.roleModes);
});
