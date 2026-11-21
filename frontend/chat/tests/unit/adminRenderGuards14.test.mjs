// Render guards for admin parts split into smaller functions: the code graph health card, the handbook report, the
// roles page, the plugins page and the workflow runs section render the same structure and make the same calls.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement, useState } from "react";
import { act, byTestId, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, plain } from "./adminGuardRenderers.mjs";
import { jsonRoutes, loadStubbed, stubs } from "./adminGuardStubLoader.mjs";
import { button, hostCount } from "./adminGuardTreeReaders.mjs";

test("the code graph health card shows counts, languages, runs, stale files and parse errors", () => {
  const { CodeGraphHealth } = loadStubbed("admin/components/projectCodeSync/CodeGraphHealth.tsx", []);
  const graphStatus = { backend: "neo4j", indexing_mode: "full", status: "ready", latest_run: { started_at: "2026-01-01T10:00:00Z" },
    summary: { file_count: 12, node_count: 30, edge_count: 40, route_count: 2, language_distribution: { ts: 9, py: 2, go: 1, rs: 1, c: 1 } },
    stale_files: [{ file_path: "a.ts", status: "changed" }], parse_errors: [{ file_path: "b.py", parse_error: "bad" }],
    run_history: [{ status: "ok", duration_ms: 12 }, { status: "failed", duration_ms: null }] };
  const view = create(createElement(CodeGraphHealth, { graphStatus }));
  includesAll(text(view.root), ["Code graph health", "neo4j · full · ", "status: ready", "files: 12", "nodes: 30", "edges: 40", "routes: 2",
    "stale: 1", "errors: 1", "ts: 9", "rs: 1", "runs: ok 12ms · failed", "stale files: a.ts (changed)", "parse errors: b.py: bad"]);
  assert.equal(text(view.root).includes("c: 1"), false);
  assert.equal(hostCount(view), 21);
  const bare = create(createElement(CodeGraphHealth, { graphStatus: { backend: "", indexing_mode: "", status: "none", latest_run: null,
    summary: null, stale_files: [], parse_errors: [], run_history: [] } }));
  includesAll(text(bare.root), ["no backend · no mode · not indexed", "files: 0", "routes: 0"]);
  assert.equal(hostCount(bare), 13);
});

const cite = { file: "m.pdf" };
const finding = (patch = {}) => ({ setting: "port", value: "80", redacted: false, component: "web", file: "a.ini", line: 3, citation: cite,
  variants: [{ path: "a.ini-test", line: 4, value: "81" }], ...patch });

test("the handbook report lists every kind of finding or says None", () => {
  const { HandbookReportView } = loadStubbed("admin/components/workspaceKnowledge/HandbookReportView.tsx", ["/EntityGraphCitation"]);
  const report = { counts: {}, undocumented_in_known_section: [finding({ resolved_value: "8080",
    name_matches: [{ parameter: "port", default: "80", citation: null }] })],
  unknown_section: [{ section: "db", component: "web", file: "b.ini", line: 1, key_count: 13, keys: Array.from({ length: 13 }, (_, i) => `k${i}`),
    variant_files: ["b.ini-x"], citation: null, name_matches: [] }],
  deviations: [finding({ redacted: true, documented: { default: "80", unit: "ms", citation: cite } })],
  unresolved_placeholders: [finding({ placeholders: ["HOST"], documented: {} })],
  inconsistencies: [{ setting: "host", values: [finding({ compared_value: "x" }), finding({ line: 9, compared_value: "80" })] }],
  documented_unused: [{ parameter: "timeout", default: "5", files: ["a.ini", "b.ini"], citation: cite }] };
  const view = create(createElement(HandbookReportView, { report, workspaceId: "w1" }));
  includesAll(text(view.root), ["Undocumented settings in sections the manual knows", "80 = 8080", "(web, a.ini line 3)",
    "also a.ini-test line 4: 81", "The manual documents the same name elsewhere:", "port (default 80)", "Citation not available to you.",
    "Sections unknown to the manual", "[db]", "13 keys — k0, k1", "k11, …", "also in b.ini-x", "Deviations from documented defaults",
    "[redacted] in web; documented", "default 80 ms", "Unresolved placeholders (not compared with the default)", "no definition of HOST",
    "Different values across components", "web: 80 = x", "Documented but never set", "timeout (default 5) — not set in a.ini, b.ini"]);
  assert.deepEqual(all(view, "section").map((node) => node.props["aria-label"]), ["Undocumented settings in sections the manual knows",
    "Sections unknown to the manual", "Deviations from documented defaults", "Unresolved placeholders", "Different values across components",
    "Documented but never set"]);
  assert.equal(stubs(view, "EntityGraphCitation").length, 7);
  assert.equal(hostCount(view), 52);
  const empty = create(createElement(HandbookReportView, { workspaceId: "w1", report: { counts: {}, undocumented_in_known_section: [],
    unknown_section: [], deviations: [], unresolved_placeholders: [], inconsistencies: [], documented_unused: [] } }));
  assert.equal(all(empty, "p").filter((node) => text(node) === "None.").length, 6);
});

test("the roles page shows the matrix, the SSO cards and a Workspace's assignments, and opens the role editor", async () => {
  const roles = [{ id: "r1", key: "dev", name: "Developer", workspace_id: null, assignment_count: 1, is_active: true, built_in: true,
    function_keys: ["code"] }, { id: "r2", key: "x", name: "Guest", workspace_id: "w2", assignment_count: 2, is_active: false, built_in: false,
    function_keys: [] }];
  const functions = [{ key: "code", name: "Write code" }, { key: "ship", name: "Ship" }];
  let calls = 0;
  const { WorkRolesPage } = loadStubbed("admin/components/workRoles/WorkRolesPage.tsx", ["/DataTable", "/AdminHeaderSlot", "./RoleEditorPanel",
    "./SsoMappingCard", "./WorkspaceRolesSection", "./WorkRolesParts"], {}, {
    "/useActiveWorkspace": { useActiveWorkspace: (projects) => useState(projects[0]?.id) },
    "./workRolesApi": { listRoles: async () => { calls += 1; return roles; }, listFunctions: async () => functions } });
  const projects = [{ id: "w1", name: "Harbor" }, { id: "w2", name: "Dock" }];
  const view = await createAsync(createElement(WorkRolesPage, { projects, isAdmin: true }));
  const table = stubs(view, "DataTable")[0].props;
  assert.deepEqual(plain(table.columns.map((column) => column.header)), ["Role", "Write code", "Ship"]);
  assert.equal(table.rows.length, 2);
  includesAll(text(create(table.columns[0].render(table.rows[1])).root), ["Guest", "Only Dock · 2 assignments"]);
  assert.deepEqual([1, 2].map((at) => text(create(table.columns[at].render(table.rows[0])).root)), ["·", "✓"]);
  includesAll(text(view.root), ["New role", "“Decide as product owner” is a function"]);
  const select = create(stubs(view, "WorkspaceRolesSection")[0].props.workspaceSelect);
  assert.equal(text(select.root), "inHarborDock");
  assert.equal(stubs(view, "WorkspaceRolesSection")[0].props.workspaceId, "w1");
  assert.equal(hostCount(view), 10);
  act(() => all(select, "select")[0].props.onChange({ target: { value: "w2" } }));
  assert.equal(stubs(view, "WorkspaceRolesSection")[0].props.workspaceName, "Dock");
  act(() => table.onOpen(table.rows[0]));
  assert.equal(stubs(view, "RoleEditorPanel")[0].props.role.id, "r1");
  assert.equal(stubs(view, "DataTable")[0].props.selectedKey, "r1");
  await act(async () => stubs(view, "RoleEditorPanel")[0].props.onSaved());
  assert.equal(calls, 2);
  const none = await createAsync(createElement(WorkRolesPage, { projects: [], isAdmin: false }));
  includesAll(text(none.root), ["Create a Workspace to assign roles in it."]);
  assert.equal(stubs(none, "AdminHeaderActions").length, 0);
});

test("the plugins page lists the image's plugins, switches one and asks for its settings", async () => {
  const item = { plugin: "jira", name: "Jira", active: false, install_id: null, needs_settings: true };
  const switched = [];
  const api = { listAvailable: async () => ({ plugins: [item], viewer: { can_activate: true } }),
    loadImageReport: async () => ({ folder: "/plugins" }), switchPlugin: async (...args) => { switched.push(args); return { id: "i1", status: "active" }; } };
  const load = (mocks) => loadStubbed("admin/components/plugins/PluginsPage.tsx", ["/EmptyLine", "/SidePanel", "./AvailablePluginList",
    "./PluginDetailPanel", "./PluginImageReport", "./PluginSettingsForm"], {}, { "./pluginsApi": { ...api, ...mocks } }).PluginsPage;
  const PluginsPage = load({});
  const view = await createAsync(createElement(PluginsPage, { mode: "workspace", workspace: { id: "w1", name: "Harbor" }, isPlatformAdmin: false }));
  includesAll(text(view.root), ["Switching one on brings its skills"]);
  assert.equal(hostCount(view), 3);
  await act(async () => stubs(view, "AvailablePluginList")[0].props.onToggle(item));
  await tick();
  assert.deepEqual(plain(switched), [["jira", "w1", true]]);
  includesAll(text(view.root), ["Jira is on. Fill in its settings"]);
  assert.equal(stubs(view, "PluginSettingsForm")[0].props.installId, "i1");
  act(() => stubs(view, "AvailablePluginList")[0].props.onOpen({ install_id: "i1" }));
  assert.equal(stubs(view, "PluginDetailPanel")[0].props.canEdit, true);
  await act(async () => button(view, "Done").props.onClick());
  assert.equal(stubs(view, "SidePanel").length, 0);
  const platform = await createAsync(createElement(load({ listAvailable: async () => ({ plugins: [], viewer: null }) }),
    { mode: "platform", workspaces: [], isPlatformAdmin: true }));
  includesAll(text(platform.root), ["A Workspace admin switches each on where it is needed."]);
  assert.equal(stubs(platform, "EmptyLine")[0].props.text.includes("(/plugins)"), true);
  assert.equal(stubs(platform, "PluginImageReport").length, 1);
  const failed = await createAsync(createElement(load({ listAvailable: async () => { throw new Error("Down"); } }),
    { mode: "platform", workspaces: [], isPlatformAdmin: false }));
  assert.equal(all(failed, "p").filter((node) => node.props.role === "alert").length, 1);
  assert.equal(stubs(failed, "EmptyLine").length, 0);
});

test("the workflow runs section lists runs by state and records an approval", async () => {
  const runs = [{ id: "r1", title: "Deploy", status: "paused", current_node_id: "n1", ticket_key: "T-1", updated_at: "2026-01-01T00:00:00Z",
    waiting_kind: "awaiting_approval", session_id: null }, { id: "r2", title: "Fix", status: "completed", current_node_id: null,
    ticket_key: null, updated_at: null, waiting_kind: null, session_id: "s 1" }];
  const { readJson, calls } = jsonRoutes({ "/api/v1/workflow-runs?": { runs },
    "/api/v1/workflow-runs/r1": (init) => (init.method === "POST" ? {} : { run: { actions: [{ key: "approve", label: "Approve" },
      { key: "cancel", label: "Cancel" }] } }) });
  const { WorkflowRunsSection } = loadStubbed("admin/components/observability/WorkflowRunsSection.tsx", ["./obUi"], {},
    { "/workflowRunModel": { ...loadStubbed("chat/workflowRun/workflowRunModel.ts", []), runsListPath: (status) => `/api/v1/workflow-runs?status=${status}`,
      runViewPath: (id) => `/api/v1/workflow-runs/${id}` } });
  const view = await createAsync(createElement(WorkflowRunsSection, { readJson }));
  includesAll(text(view.root), ["Workflow runs", "Workflow", "Deploy", "n1", "T-1", "Decide", "Fix", "Open the run"]);
  assert.equal(all(view, "a")[0].props.href, "/chat?session_id=s%201");
  assert.equal(hostCount(view), 32);
  await act(async () => button(view, "Decide").props.onClick());
  assert.deepEqual(buttons(view), ["Approve"]);
  await act(async () => button(view, "Approve").props.onClick());
  await tick();
  assert.deepEqual(plain(calls.map((call) => [call.method, call.url])), [["GET", "/api/v1/workflow-runs?status=attention"],
    ["GET", "/api/v1/workflow-runs/r1"], ["POST", "/api/v1/workflow-runs/r1/actions"], ["GET", "/api/v1/workflow-runs?status=attention"]]);
  await act(async () => stubs(view, "Segmented")[0].props.onChange("done"));
  await tick();
  assert.equal(calls.at(-1).url, "/api/v1/workflow-runs?status=done");
  const noDecision = await createAsync(createElement(WorkflowRunsSection, { readJson: jsonRoutes({ "/api/v1/workflow-runs?": { runs: [runs[0]] },
    "/api/v1/workflow-runs/r1": { run: { actions: [] } } }).readJson }));
  await act(async () => button(noDecision, "Decide").props.onClick());
  includesAll(text(noDecision.root), ["Another admin decides (approval rule: four-eyes)."]);
  const empty = await createAsync(createElement(WorkflowRunsSection, { readJson: jsonRoutes({ "/api/v1/workflow-runs?": { runs: [] } }).readJson }));
  includesAll(text(empty.root), ["No workflow run in this state."]);
});
