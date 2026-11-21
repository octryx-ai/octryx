// Render guards for admin parts split into smaller functions: the episode policy switches, a decision's drawer, the
// policy engine status drawer, a Workspace's skills, the grouped knowledge search hits and the Workspace access
// tables render the same structure and call the same handlers.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, plain } from "./adminGuardRenderers.mjs";
import { jsonRoutes, loadStubbed, stubs } from "./adminGuardStubLoader.mjs";
import { button, hostCount } from "./adminGuardTreeReaders.mjs";

test("the episode policy panel shows the switches, the read-only keys and toggles a switch", async () => {
  const puts = [];
  const real = loadStubbed("admin/components/workspaceKnowledge/episodePolicy.ts", []);
  const settings = { workspace_id: "w1", may_author: true, public_origin_configured: false, accept_session_episodes: true,
    capture_platform_turns: false, legacy_flag: { a: 1 } };
  const api = { get: async () => settings, put: async (id, body) => { puts.push([id, body]); return { ...settings, ...body }; } };
  const { KnowledgeEpisodePolicyPanel } = loadStubbed("admin/components/workspaceKnowledge/KnowledgeEpisodePolicyPanel.tsx", [], {},
    { "./episodePolicy": { ...real, episodePolicyApi: api } });
  const view = await createAsync(createElement(KnowledgeEpisodePolicyPanel, { workspaceId: "w1" }));
  includesAll(text(view.root), ["Session episodes", "Episodes are refused until a platform operator", "Other policy keys (read-only)",
    "legacy_flag", "{\"a\":1}", "Saving a switch keeps these values unchanged."]);
  const switches = view.root.findAll((node) => node.type === "button" && node.props.role === "switch");
  assert.deepEqual(switches.map((node) => node.props["aria-checked"]), [true, false]);
  assert.equal(hostCount(view), 30);
  await act(async () => switches[1].props.onClick());
  assert.equal(puts[0][0], "w1");
  assert.equal(puts[0][1].capture_platform_turns, true);
  const reader = { get: async () => ({ may_author: false, public_origin_configured: true }), put: async () => settings };
  const { KnowledgeEpisodePolicyPanel: Reader } = loadStubbed("admin/components/workspaceKnowledge/KnowledgeEpisodePolicyPanel.tsx", [], {},
    { "./episodePolicy": { ...real, episodePolicyApi: reader } });
  includesAll(text((await createAsync(createElement(Reader, { workspaceId: "w1" }))).root), ["The server returned no episode switches.",
    "Only a workspace admin or owner can change these switches."]);
  const failing = { get: async () => { throw new Error("Forbidden"); } };
  const { KnowledgeEpisodePolicyPanel: Failing } = loadStubbed("admin/components/workspaceKnowledge/KnowledgeEpisodePolicyPanel.tsx", [], {},
    { "./episodePolicy": { ...real, episodePolicyApi: failing } });
  assert.equal(text((await createAsync(createElement(Failing, { workspaceId: "w1" }))).root), "Forbidden");
});

test("the decision drawer shows outcome, why, the lifecycle and the request, and links to the run and the rule", async () => {
  const opened = [], runs = [], assigned = [];
  const detail = { id: "d1", time: "2026-01-02T03:04:05Z", outcome: "denied", gate: "cedar", what: "Write file", who: "Ann", decided_by: "Bob",
    workspace_name: null, mode: "enforce", subtitle: "Too wide", rule: "no-writes", rule_code: "R1", reason: "Policy", approval_id: "ap-1",
    run_exists: true, run_key: "run-1", content: { files: 2 }, obligation: null,
    lifecycle: [{ id: "l1", time: "2026-01-02T03:04:05Z", who: "Ann", decided_by: null, reason: "", outcome: "pending" },
      { id: "l2", time: "2026-01-02T04:04:05Z", who: "Ann", decided_by: "Bob", reason: "No", outcome: "denied" }] };
  const load = (answer) => loadStubbed("admin/components/observability/DecisionDrawer.tsx", ["../projectsTab/SettingsDrawer"],
    { window: { location: { assign: (href) => assigned.push(href) } } },
    { "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) } }).DecisionDrawer;
  const { readJson } = jsonRoutes({ "/api/v1/observability/decisions/d1": detail });
  const view = await createAsync(createElement(load(), { decisionId: "d1", readJson, onClose() {}, onOpenRun: (key) => runs.push(key) }));
  const drawer = stubs(view, "SettingsDrawer")[0].props;
  assert.equal(drawer.title, "Write file");
  assert.match(drawer.eyebrow, /^Decision · .+ · /);
  includesAll(text(view.root), ["Outcome", "Gate", "Who · where", "Bob · global", "Engine mode", "enforce", "Why", "Too wide", "no-writes", "R1",
    "Policy", "The reason given at the time is kept", "Rules are edited in Admin › Rules › Policies.", "Approval lifecycle",
    "requested by Ann", "by Bob · No", "Request (counts only)", "\"files\": 2", "Open approval", "Open run", "Edit rule in Admin › Rules › Policies"]);
  assert.equal(byTestId(view, "decision-open-approval").length, 1);
  assert.equal(hostCount(view), 38);
  act(() => button(view, "Open run").props.onClick());
  act(() => button(view, "Edit rule in Admin › Rules › Policies").props.onClick());
  assert.deepEqual([runs, opened], [["run-1"], ["cedarPolicies"]]);
  const device = jsonRoutes({ "/api/v1/observability/decisions/d2": { ...detail, gate: "device_job", lifecycle: [], content: null,
    approval_id: null, run_exists: false } }).readJson;
  const other = await createAsync(createElement(load(), { decisionId: "d2", readJson: device, onClose() {}, onOpenRun() {} }));
  assert.equal(button(other, "Open run").props.disabled, true);
  act(() => button(other, "Edit rule in Agents › Connected clients").props.onClick());
  assert.deepEqual(assigned, ["/chat?area=agents"]);
  assert.equal(text(other.root).includes("Approval lifecycle"), false);
  const broken = await createAsync(createElement(load(), { decisionId: "x", readJson: async () => { throw new Error("gone"); }, onClose() {}, onOpenRun() {} }));
  assert.equal(all(broken, "div").filter((node) => node.props.role === "alert").length, 1);
});

const status = (patch = {}) => ({ mode: "shadow", engineAvailable: false, schemaVersion: "s1", customVersion: 3, customValid: false,
  customFallbacks: 4, baselineDigest: "", workspaces: 1, p95Ms: 1.25, samples: 10, draftP95Ms: 0.5, draftSamples: 2, retentionDays: 30,
  pending: 0, dropped: 0, counters: { seat: { match: 5, mismatch: 1 }, custom: { error: 2 } },
  enforce: { windowHours: 24, shadowSince: null, mismatches: 1, errors: 2, ready: false, reasons: ["engine_unavailable"] }, ...patch });

test("the policy engine drawer shows KPIs, modes with the readiness, counters and settings, and saves", async () => {
  const saved = [], changed = [];
  const api = { saveEngineSettings: async (body) => { saved.push(["settings", body]); }, saveEngineMode: async (mode) => { saved.push(["mode", mode]); return {}; } };
  const { PolicyEngineStatusDrawer } = loadStubbed("admin/components/policyEngine/PolicyEngineStatusCard.tsx", ["../projectsTab/SettingsDrawer"], {},
    { "./policyEngineApi": api });
  const view = create(createElement(PolicyEngineStatusDrawer, { status: status(), onChanged: (next) => changed.push(next), onClose() {} }));
  includesAll(text(view.root), ["Mode", "Shadow", "schema s1", "Mismatches", "in the 24 h window", "p95 latency", "1.3 ms",
    "over 10 decisions · draft shadow +0.5 ms", "The Cedar engine is not available", "4 decisions evaluated without them",
    "Enforce is not ready: The Cedar engine is not available on this server. Enforcement unlocks after 24 hours",
    "Decisions per check (since the server started)", "Seat sessions", "custom", "5 agreements, 1 disagreements, 2 errors. Decision log kept 30 days.",
    "Enforce window (hours)", "Decision log retention (days)", "Close", "Save"]);
  assert.deepEqual(all(view, "th").map((node) => text(node)), ["Check", "Agrees", "Custom policy denies", "Disagrees", "Error (denied)"]);
  assert.equal(byTestId(view, "policy-engine-mode-enforce")[0].props.disabled, true);
  assert.equal(byTestId(view, "policy-engine-mode-save")[0].props.disabled, true);
  assert.equal(hostCount(view), 66);
  act(() => byTestId(view, "policy-engine-mode-off")[0].props.onClick());
  act(() => byTestId(view, "policy-engine-window")[0].props.onChange({ target: { value: "48" } }));
  await act(async () => byTestId(view, "policy-engine-mode-save")[0].props.onClick());
  assert.deepEqual(plain(saved), [["settings", { enforce_window_hours: 48, decision_log_retention_days: 30 }], ["mode", "off"]]);
  assert.equal(text(byTestId(view, "policy-engine-message")[0]), "Saved.");
  const ready = create(createElement(PolicyEngineStatusDrawer, { status: status({ engineAvailable: true, customValid: true, draftSamples: 0,
    enforce: { windowHours: 24, shadowSince: "2026-01-01T00:00:00Z", mismatches: 0, errors: 0, ready: true, reasons: [] } }), onChanged() {}, onClose() {} }));
  assert.equal(byTestId(ready, "policy-engine-blockers").length, 0);
  assert.equal(all(ready, "div").filter((node) => node.props.role === "alert").length, 0);
});

test("the Workspace skills section shows the picker, the surfaces and saves or discards the draft", async () => {
  const calls = [], opened = [];
  const assignment = { digest: "d1", categories: [], skills: [],
    policy: { mode: "all_active", skill_ids: [], category_keys: [], blocked_skill_ids: [], surfaces: { platform_chat: true, octryx_claude: false } } };
  const api = { loadAssignment: async (id) => { calls.push(["load", id]); return assignment; },
    saveAssignment: async (...args) => { calls.push(["save", ...args]); return assignment; } };
  const { ProjectSkillsSection } = loadStubbed("admin/components/projectsTab/ProjectSkillsSection.tsx",
    ["./WorkspaceEffectiveSkills", "./WorkspaceSkillsPicker"], {},
    { "../skillCatalog/skillCatalogApi": api, "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) } });
  const view = await createAsync(createElement(ProjectSkillsSection, { ctx: { configuringProjectQuality: { id: "p1", name: "Shop" } } }));
  includesAll(text(view.root), ["Skills", "Open skill catalog", "Which skills this Workspace gets", "Surfaces in this Workspace",
    "Agents in this Workspace can search", "Assigned skills are delivered to Claude Code sessions", "Save", "Discard"]);
  assert.deepEqual(byTestId(view, "ws-surface-platform_chat").concat(byTestId(view, "ws-surface-octryx_claude")).map((node) => node.props["aria-checked"]),
    [true, false]);
  assert.equal(byTestId(view, "ws-save")[0].props.disabled, true);
  assert.equal(hostCount(view), 24);
  act(() => byTestId(view, "ws-surface-octryx_claude")[0].props.onClick());
  includesAll(text(view.root), ["Unsaved changes"]);
  assert.equal(stubs(view, "WorkspaceEffectiveSkills")[0].props.dirty, true);
  await act(async () => byTestId(view, "ws-save")[0].props.onClick());
  assert.deepEqual(calls.map(([name]) => name), ["load", "save"]);
  assert.equal(calls[1][3], "d1");
  includesAll(text(view.root), ["Saved. The effective skills below are recomputed."]);
  act(() => byTestId(view, "ws-open-catalog")[0].props.onClick());
  assert.deepEqual(opened, ["skills"]);
  const none = await createAsync(createElement(ProjectSkillsSection, { ctx: {} }));
  includesAll(text(none.root), ["Loading the Workspace skills…"]);
  assert.deepEqual(buttons(none), ["Open skill catalog"]);
});

const hit = (key, patch = {}) => ({ evidence_key: key, source_title: `Page ${key}`, text: `Text of ${key}`, source_id: "s1", revision_id: `r${key}`,
  bound: false, products: [], version: "", container: "ENG", origin: { kind: "confluence" }, changed_at: "2026-01-01T00:00:00Z", ...patch });

test("the hit groups show each source group with its hits, passages and older versions", () => {
  const chosen = [];
  const { KnowledgeHitGroups } = loadStubbed("admin/components/workspaceKnowledge/search/KnowledgeHitGroups.tsx", ["/TimeText", "./SnippetMarkdown"]);
  const shown = [
    { hit: hit("a", { text: `${"word ".repeat(200)}end`, origin: { kind: "confluence", url: "https://wiki/a" } }), number: 1,
      older: [hit("a0")], passages: [hit("a2"), hit("a3")] },
    { hit: hit("b", { origin: { kind: "jira" }, container: null }), number: 2, older: [] },
  ];
  const props = { shown, workspaceId: "w1", selectedKey: "a0", onSelect: (value) => chosen.push(value.evidence_key), labelledBy: "lbl", terms: ["end"] };
  const view = create(createElement(KnowledgeHitGroups, props));
  includesAll(text(view.root), ["Confluence", "Jira", "Page a", "Page b", "ENG", "Show full passage", "Preview", "Open in Confluence",
    "+2 more passages", "Hide older versions", "Page a0", "Open original"]);
  assert.equal(all(view, "section").length, 2);
  assert.equal(all(view, "li").filter((node) => node.props.className?.includes("--selected")).length, 1);
  assert.equal(hostCount(view), 39);
  act(() => byTestId(view, "search-more-passages")[0].props.onClick());
  assert.equal(byTestId(view, "search-passage").length, 2);
  act(() => button(view, "Show full passage").props.onClick());
  includesAll(text(view.root), ["Show less"]);
  act(() => button(view, "Page a0").props.onClick());
  act(() => byTestId(view, "search-passage")[1].findAll((node) => node.type === "button")[0].props.onClick());
  assert.deepEqual(chosen, ["a0", "a3"]);
  const single = create(createElement(KnowledgeHitGroups, { ...props, shown: [shown[1]], selectedKey: null }));
  assert.equal(all(single, "h3").filter((node) => node.props.className === "knowledge-search__group-head").length, 0);
  assert.equal(all(single, "ol")[0].props["aria-labelledby"], "lbl");
});

const user = { id: "u1", username: "ada", email: "ada@example.com", display_name: "Ada", is_active: false, roles: ["operator"], groups: ["Ops"] };

test("the access tables list users, roles and groups with their Workspace roles, a picker for a new row and Remove", () => {
  const calls = [];
  const record = (name) => (...args) => calls.push([name, ...args]);
  const tables = loadStubbed("admin/components/projectsTab/ProjectAccessTables.tsx", ["./ProjectRoleChips"]);
  const handlers = { onUpdate: record("update"), onRemove: record("remove"), onAdd: record("add") };
  const payload = { available_roles: [{ id: "r1", name: "operator", description: "Runs things" }],
    available_groups: [{ id: "g1", name: "Ops", description: "", is_active: false }], rules: ["Rule one", "Rule two"] };
  const users = create(createElement(tables.DirectUserAccessTable, { rows: [{ key: "k1", user_id: "u1", project_roles: ["owner"] },
    { key: "k2", user_id: "", project_roles: [] }], userById: { u1: user }, availableUsersForRow: () => [{ id: "u2", username: "bob", display_name: "" }], ...handlers }));
  includesAll(text(users.root), ["Direct user access", "+ Add user", "User", "Ada", "ada · ada@example.com · inactive", "operator", "Ops",
    "Select user", "bob"]);
  assert.deepEqual(stubs(users, "ProjectRoleChips").map((node) => [node.props.label, node.props.disabled]),
    [["Workspace roles for Ada", false], ["Workspace roles for new user", true]]);
  assert.equal(hostCount(users), 39);
  act(() => all(users, "select")[0].props.onChange({ target: { value: "u2" } }));
  act(() => stubs(users, "ProjectRoleChips")[0].props.onChange(["viewer"]));
  act(() => all(users, "button").find((node) => node.props["aria-label"] === "Remove Ada").props.onClick());
  const roles = create(createElement(tables.RoleAccessTable, { rows: [{ key: "k3", role_id: "r1", project_roles: [] }, { key: "k4", role_id: "", project_roles: [] }],
    payload, availableRolesForRow: () => payload.available_roles, ...handlers }));
  includesAll(text(roles.root), ["By global role", "operator", "Runs things", "Select role", "—"]);
  assert.equal(hostCount(roles), 35);
  const groups = create(createElement(tables.GroupAccessTable, { rows: [{ key: "k5", group_id: "g1", project_roles: [] }], payload,
    availableGroupsForRow: () => [], ...handlers }));
  includesAll(text(groups.root), ["By group", "Ops", "No description", "Inactive", "Rule one", "Rule two"]);
  assert.equal(all(groups, "button").find((node) => node.props["aria-label"] === "Remove Ops").props.disabled, false);
  assert.equal(hostCount(groups), 28);
  const empty = create(createElement(tables.GroupAccessTable, { rows: [], payload: { ...payload, rules: [] }, availableGroupsForRow: () => [], ...handlers }));
  includesAll(text(empty.root), ["No group grants access."]);
  assert.deepEqual(plain(calls), [["update", "k2", { user_id: "u2" }], ["update", "k1", { project_roles: ["viewer"] }], ["remove", "k1"]]);
});
