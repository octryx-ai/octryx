// Render guards for admin settings parts split into smaller functions: workspace access, the live operations page,
// a code repository card, the research strategy fields, the knowledge access view, workspace memory, usage & costs
// and a function's tool set render the same structure after being split up.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { load } from "./adminPartsLoader.mjs";
import { act, byTestId, server, text, tick } from "./settingsRenderHarness.mjs";

const noop = () => {};

function create(element) {
  let view;
  act(() => { view = TestRenderer.create(element); });
  return view;
}

async function createAsync(element) {
  let view;
  await act(async () => { view = TestRenderer.create(element); });
  await tick();
  return view;
}

const all = (view, type) => view.root.findAll((node) => node.type === type);

test("workspace access loads the assignments, counts them and saves the drafts", async () => {
  const { ProjectAccessSection } = load("admin/components/projectsTab/ProjectAccessSection.tsx");
  const calls = [];
  const payload = {
    available_users: [{ id: "u1", username: "ada", email: "ada@example.com", display_name: "Ada", is_active: true, roles: ["operator"], groups: [] },
      { id: "u2", username: "bob", email: "bob@example.com", display_name: "", is_active: false, roles: [], groups: ["Ops"] }],
    available_roles: [{ id: "r1", name: "operator" }], available_groups: [], group_assignments_supported: false,
    assignments: [{ user_id: "u1", project_roles: ["owner"] }], group_assignments: [], role_assignments: [{ role_id: "r1", project_roles: ["viewer"] }],
    rules: [],
  };
  const readJson = async (url, init) => { calls.push([url, init?.method || "GET", init?.body ? JSON.parse(init.body) : null]); return payload; };
  const view = await createAsync(createElement(ProjectAccessSection, { ctx: { configuringProjectQuality: { id: "p 1" }, readJson } }));
  const page = text(view.root);
  for (const part of ["Workspace access", "Refresh", "Open Platform access", "1 users (1 active)", "1 global roles", "0 groups",
    "Changes apply after saving.", "Save workspace access"]) assert.ok(page.includes(part), part);
  assert.equal(calls[0][0], "/admin/chat/api/panel/projects/p%201/access");
  const buttons = all(view, "button").map((node) => text(node));
  assert.ok(buttons.includes("Save workspace access"));
  const save = all(view, "button").find((node) => text(node) === "Save workspace access");
  await act(async () => { save.props.onClick(); });
  await tick();
  assert.deepEqual(calls[1].slice(0, 2), ["/admin/chat/api/panel/projects/p%201/access", "PUT"]);
  assert.deepEqual(calls[1][2].assignments.map((row) => row.user_id), ["u1"]);
  assert.deepEqual(calls[1][2].role_assignments.map((row) => row.role_id), ["r1"]);
  act(() => view.unmount());

  const empty = await createAsync(createElement(ProjectAccessSection, { ctx: { configuringProjectQuality: null, readJson } }));
  assert.ok(!text(empty.root).includes("Save workspace access"));
  act(() => empty.unmount());
});

const livePayload = {
  generated_at: "2026-01-01T10:00:00Z", viewer: { id: "me" },
  counts: { working: 1, needs_you: 0, silent: 0, looping: 0, problem: 1, stopped: 0, cost_24h_usd: 1.5 },
  runs: [{ id: "run1", workflow_title: "Fix login", state: "problem", status: "running", last_event_at: "2026-01-01T09:59:00Z",
    idle_seconds: 30, cost_usd: 0.4, session_id: "s1", workspace: { id: "w1", name: "W" },
    current_node: { title: "Implement" },
    problems: [{ key: "p:loop", severity: "problem", title: "Loops" }],
    items: [{ id: "i1", title: "Item one", status: "running", session_id: "s2", problems: [] }] }],
  devices: [{ id: "d1", name: "Mac", online: true, jobs_running: 1, max_parallel_jobs: 2 }],
  seats: [{ user: { id: "me", name: "Me" }, five_hour_pct: 10, seven_day_pct: 20 }],
};

test("operations live shows the toolbar, the runs with their open item rows, devices and seats", async () => {
  const srv = server((call) => (call.url.includes("/operations/live") ? { status: 200, body: livePayload } : { status: 200, body: {} }));
  const { OperationsLivePage } = load("admin/components/operations/OperationsLivePage.tsx", { fetch: srv.fetch });
  const view = await createAsync(createElement(OperationsLivePage, { projects: [{ id: "w1", name: "W", is_default: true }], currentUserId: "me" }));
  await tick();
  const page = text(view.root);
  for (const part of ["Refresh", "Runs", "Fix login", "Item one", "Implement", "Devices", "Seats", "Mac"]) assert.ok(page.includes(part), part);
  assert.equal(byTestId(view, "operations-live").length, 1);
  assert.ok(srv.calls.some((call) => call.url.includes("/operations/live")));
  assert.deepEqual(all(view, "th").map((node) => text(node)).slice(0, 7),
    ["Run", "State", "Step", "Where", "Last sign of life", "API cost · seat", "Action"]);
  assert.equal(byTestId(view, "ops-open").length, 1);
  act(() => view.unmount());

  const none = create(createElement(OperationsLivePage, { projects: [{ id: "a", name: "A" }, { id: "b", name: "B" }] }));
  assert.equal(byTestId(none, "operations-live").length, 1);
  assert.equal(byTestId(none, "ops-runs").length, 0);
  act(() => none.unmount());
});

const repo = (patch = {}) => ({
  id: "r1", project_id: "p1", name: "core", provider: "git", repo_root: "/src/core", last_index_status: "ready",
  index_backend: "bm25", semantic_backend: "none", structure_backend: "ast", graph_backend: "local",
  last_indexed_at: null, last_index_error: "", effective_backends: { index: "bm25" },
  latest_index_summary: { file_count: 12, symbol_count: 40, languages: { python: 10, go: 2 } },
  backend_status: { index: { ready: true, available: true, effective: "bm25", mode: "primary", configured: "auto", detail: "" },
    semantic: { ready: false, available: false, effective: "none", mode: "disabled", detail: "off" } },
  ...patch,
});

test("a code repository card shows the local index details and its actions", () => {
  const { CodeRepositoryCard } = load("admin/components/projectCodeSync/CodeRepositoryCard.tsx");
  const edits = [];
  const props = { projectCodeRepositoryRunningId: null, projectCodeRepositoryLoading: false,
    handleEditProjectCodeRepository: (r) => edits.push(r.id), handleRunProjectCodeIndex: async () => {}, handleDeleteProjectCodeRepository: async () => {} };
  const local = create(createElement(CodeRepositoryCard, { ...props, repo: repo() }));
  const page = text(local.root);
  for (const part of ["core", "git", "ready", "/src/core", "last index: never", "files: 12", "symbols: 40", "python: 10",
    "Search: bm25", "Semantic: none (off)", "Rebuild Index", "Delete", "effective: search bm25"]) assert.ok(page.includes(part), part);
  assert.equal(all(local, "button").length, 3);
  all(local, "button")[0].props.onClick();
  assert.deepEqual(edits, ["r1"]);
});

test("the research strategy section renders its eight fields and writes their paths", () => {
  const { ResearchPolicyStrategySection } = load("admin/components/researchPolicies/ResearchPolicyStrategySection.tsx");
  const numbers = [];
  const paths = [];
  const spec = { research_strategy: { mode: "deep", max_search_rounds: 6 }, output_policy: { citation_style: "apa" } };
  const view = create(createElement(ResearchPolicyStrategySection, { spec, parseError: "",
    setPath: (...args) => paths.push(args), setNumberPath: (...args) => numbers.push(args) }));
  assert.equal(all(view, "label").length, 16);
  assert.equal(all(view, "select").length, 2);
  const inputs = all(view, "input");
  assert.deepEqual(inputs.map((node) => node.props.value), [1, 10, 24, 6, 8, 3]);
  assert.deepEqual(inputs.map((node) => node.props.max), [undefined, undefined, undefined, 20, undefined, 5]);
  assert.equal(all(view, "select")[0].props.value, "deep");
  inputs[3].props.onChange({ target: { value: "7" } });
  assert.equal(JSON.stringify(numbers[0]), JSON.stringify([["research_strategy", "max_search_rounds"], "7", 4]));
  all(view, "select")[1].props.onChange({ target: { value: "ieee" } });
  assert.equal(JSON.stringify(paths[0]), JSON.stringify([["output_policy", "citation_style"], "ieee"]));
});

test("the knowledge access view shows the owned base, the workspace switch and the mounts", () => {
  const { ProjectKnowledgeAccessView } = load("admin/components/projectsTab/ProjectKnowledgeAccessView.tsx");
  const removed = [];
  const props = {
    payload: { knowledge_base: { project_name: "Core KB" }, knowledge_mounts: [{ source_project_id: "s1", source_project_name: "Other", mount_label: "" }] },
    saving: false, knowledgeAccess: { mode: "x", default_workspace_access: true }, toggleWorkspaceKnowledgeAccess: noop,
    removeKnowledgeMount: (id) => removed.push(id), selectedMountProjectId: "", setSelectedMountProjectId: noop, mountLabel: "",
    setMountLabel: noop, availableKnowledgeBases: [{ project_id: "k2", project_name: "Second" }], addKnowledgeMount: noop,
  };
  const view = create(createElement(ProjectKnowledgeAccessView, props));
  const page = text(view.root);
  for (const part of ["Knowledge base access", "Core KB", "owned", "default", "Read central workspace Knowledge", "Knowledge mounts",
    "Other", "Source: Other", "Mount source", "Second", "Add mount"]) assert.ok(page.includes(part), part);
  assert.ok(!page.includes("No knowledge mounts are configured."));
  all(view, "button").find((node) => text(node) === "Remove").props.onClick();
  assert.deepEqual(removed, ["s1"]);
  assert.equal(all(view, "button").find((node) => text(node) === "Add mount").props.disabled, true);
  const bare = create(createElement(ProjectKnowledgeAccessView, { ...props, availableKnowledgeBases: [],
    payload: { ...props.payload, knowledge_mounts: [] }, knowledgeAccess: { mode: "x", default_workspace_access: false } }));
  const barePage = text(bare.root);
  for (const part of ["limited", "No knowledge mounts are configured.", "No additional active project knowledge bases"]) assert.ok(barePage.includes(part), part);
});

const memoryItem = (patch) => ({ id: "m1", kind: "memory", scope: "workspace", class: "team_decision", author_class: "human_stated",
  state: "observed", product: null, text: "Use squash merges", recorded_by: "Ada", present_as: "from session of Ada", session_id: null,
  session_link: null, supersedes_id: null, created_at: null, expires_at: null, state_changed_at: null, may_change: true, ...patch });

test("workspace memory shows its switches, the lesson roles and one row per memory with its actions", async () => {
  const overview = { workspace_id: "w1", may_author: true, automatic_capture: false, session_lessons: true, confirm_roles: ["owner"],
    items: [memoryItem({}), memoryItem({ id: "m2", state: "proposed", text: null, may_change: true }), memoryItem({ id: "m3", state: "confirmed", may_change: false })] };
  const srv = server((call) => (call.url.includes("/feedback") ? { status: 200, body: { items: [], by_workflow: [], by_aspect: [], total: 0 } }
    : { status: 200, body: overview }));
  const { KnowledgeMemoryPanel } = load("admin/components/workspaceKnowledge/KnowledgeMemoryPanel.tsx", { fetch: srv.fetch });
  const view = await createAsync(createElement(KnowledgeMemoryPanel, { workspaceId: "w1" }));
  const page = text(view.root);
  for (const part of ["Show superseded and forgotten", "Capture memories automatically", "Propose lessons learned", "Viewer", "Platform admin",
    "Use squash merges", "stated by a person", "proposed lesson", "Forgotten: the text was erased.", "Answer feedback"]) assert.ok(page.includes(part), part);
  assert.deepEqual(all(view, "th").map((node) => text(node)).slice(0, 6), ["Memory", "Scope", "Class", "Author", "State", ""]);
  assert.equal(all(view, "tbody")[0].findAll((node) => node.type === "tr").length, 3);
  const roleBoxes = byTestId(view, "memory-session-lessons")[0].findAll((node) => node.type === "input");
  assert.deepEqual(roleBoxes.map((node) => node.props.checked), [true, false, false, true, false]);
  const actions = all(view, "button").map((node) => text(node));
  assert.deepEqual(actions.filter((label) => ["Confirm", "Reject", "Correct", "Forget"].includes(label)),
    ["Confirm", "Correct", "Forget", "Confirm", "Reject", "Forget"]);
  await act(async () => { all(view, "button").find((node) => text(node) === "Correct").props.onClick(); });
  assert.equal(all(view, "textarea").length, 1);
  assert.ok(all(view, "button").some((node) => text(node) === "Save"));
  act(() => view.unmount());
});

const usage = {
  window: "month", since: "2026-01-01T00:00:00Z", until: "2026-01-31T00:00:00Z",
  tiles: { spend: 12.5, priced_coverage: 0.8, unpriced_tokens: 200, platform_billed_tokens: 1000, tokens: 1200, cache_tokens: 100, active_users: 3 },
  unpriced_policy: "block", daily: [{ day: "2026-01-01", spend: 1 }],
  by_model: [{ provider: "openai", model: "gpt-x", tokens: 800, unpriced_tokens: 0, cost: 12.5, pricing: "priced" },
    { provider: "local", model: "llama", tokens: 200, unpriced_tokens: 200, cost: 0, pricing: "unpriced" }],
  by_workspace: [{ workspace_id: "w1", workspace_name: "W", runs: 4, cost: 12.5, budget: { name: "m", limit: 100, used: 12.5, percent: 13 } },
    { workspace_id: null, workspace_name: null, runs: 1, cost: 0, budget: null }],
  by_user: [{ user_id: "u1", user_name: "Ada", runs: 5, cost: 12.5 }],
  budgets: [{ limit: "Monthly", scope: "Platform", cap: 100, used: 12.5, percent: 13 }],
};

test("usage & costs shows the window, the pricing warning, the tiles and the four tables", async () => {
  const urls = [];
  const readJson = async (url) => { urls.push(url); return usage; };
  const { ObservabilityUsagePage } = load("admin/components/observability/ObservabilityUsagePage.tsx");
  const view = await createAsync(createElement(ObservabilityUsagePage, { projects: [], readJson }));
  assert.deepEqual(urls, ["/api/v1/observability/usage?window=month"]);
  const page = text(view.root);
  for (const part of ["Costs per run and outcome", "no price", "llama", "new runs on an unpriced model are refused", "Spend (priced)",
    "Priced coverage", "Tokens", "Active users", "By model", "By Workspace", "No Workspace", "no budget",
    "By user (top 5)", "Ada", "Limits & budgets", "Edit in Models › Budgets"]) assert.ok(page.includes(part), part);
  assert.equal(byTestId(view, "usage-pricing-warning").length, 1);
  assert.equal(all(view, "table").length, 4);
  assert.equal(view.root.findAll((node) => node.type === "div" && node.props.role === "meter").length, 2);
  assert.deepEqual(all(view, "tbody").map((node) => node.findAll((child) => child.type === "tr").length), [2, 2, 1, 1]);
  act(() => view.unmount());
});

test("a function's tool set lists groups, risks, selectors and patterns, and keeps details across tabs", async () => {
  const fn = { id: "f1", key: "dev", name: "Developer", description: "Builds", workspace_id: "w1", built_in: false,
    tools: ["jira_read", "jira_*", "ghost_tool"], tools_version: 2, version: 3, role_keys: [] };
  const catalog = { selectors: [{ entry: "connector:jira:read", label: "Every Jira read tool" }], unknown_entries: ["ghost_tool"],
    groups: [{ connector: "jira", label: "Jira", risks: { read: [{ name: "jira_read", description: "Read issues", in_set: true }],
      write: [{ name: "jira_write", description: "Write issues", in_set: false }] } }] };
  const srv = server(() => ({ status: 200, body: catalog }));
  const { ToolSetPanel } = load("admin/components/workRoles/ToolSetPanel.tsx", { fetch: srv.fetch });
  const view = await createAsync(createElement(ToolSetPanel, { fn, roleNames: ["Dev"], canEdit: true, onClose: noop, onSaved: noop }));
  const page = text(view.root);
  for (const part of ["Developer", "In Dev", "Whole groups", "Every Jira read tool", "Jira", "Patterns and other entries", "jira_*",
    "Matches no tool today.", "Select all", "Save tools"]) assert.ok(page.includes(part), part);
  assert.equal(byTestId(view, "unknown-entries").length, 1);
  assert.equal(byTestId(view, "tools-save")[0].props.disabled, true);
  assert.equal(view.root.findAll((node) => node.type === "section" && node.props.className === "wr-tools-group").length, 1);
  assert.equal(view.root.findAll((node) => node.type === "div" && node.props.className === "wr-tools-risk").length, 2);
  const newEntry = view.root.findAll((node) => node.type === "input" && node.props["aria-label"] === "New entry")[0];
  await act(async () => { newEntry.props.onChange({ target: { value: "confluence_*" } }); });
  const panel = view.root.findAll((node) => node.props.testId === "tool-set-panel")[0];
  await act(async () => { panel.props.tabs.onChange("details"); });
  const name = view.root.findAll((node) => node.type === "input")[0];
  assert.equal(name.props.value, "Developer");
  await act(async () => { name.props.onChange({ target: { value: "Dev 2" } }); });
  await act(async () => { panel.props.tabs.onChange("tools"); });
  assert.equal(view.root.findAll((node) => node.type === "input" && node.props["aria-label"] === "New entry")[0].props.value, "confluence_*");
  await act(async () => { panel.props.tabs.onChange("details"); });
  assert.equal(view.root.findAll((node) => node.type === "input")[0].props.value, "Dev 2");
  act(() => view.unmount());
});
