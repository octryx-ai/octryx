// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards05.test.mjs
//
// Render guards for admin panels, cards and inspectors whose long functions are split into smaller parts: each renders
// with representative props, keeps its key labels and test ids, and keeps its whole rendered tree (a digest of the
// test renderer's JSON), so the split draws exactly what the original drew.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement as h } from "react";
import { act, digest, mount, noop, server, text } from "./adminDigestRenderHarness.mjs";

// --- Flow inspector -------------------------------------------------------------------------------------------------

test("flow inspector: empty, a schema-configured tool step with contract and catalog binding, and each step kind", async () => {
  const path = "admin/components/flowBuilder/FlowInspector.tsx";
  const contract = {
    type: "tool_step", display_name: "Tool", category: "action", description: "Calls a tool", config_schema: {}, input_schema: {},
    output_schema: {}, can_start: false, can_end: true, can_pause: true, calls_tools: true, calls_llm: false,
    required_config_keys: ["tool"], required_config_any: ["a", "b"], security_requirements: ["approval"], project_visibility_implications: [],
  };
  const catalogItem = {
    id: "tool:search", node_type: "tool_step", binding_type: "tool", binding_ref: "search", display_name: "Search", category: "tools",
    icon_hint: "", description: "Searches", config_schema: { properties: { query: { type: "string", title: "Query" } } }, input_schema: {},
    output_schema: {}, availability_status: "disabled", disabled_reason: "No connector", permission_requirements: [],
    token_cost_risk: "low", evidence_behavior: "Keeps hits", audit_behavior: "Audited", default_config: {},
  };
  const base = { onUpdate: noop, onValidateConfig: noop, agents: [{ id: "a-1", name: "Coder" }], tools: [{ name: "search" }] };
  const empty = await mount(path, "FlowInspector", { ...base, node: null });
  assert.match(text(empty.root), /Select a node/);
  const tool = await mount(path, "FlowInspector", {
    ...base, nodeContracts: [contract], nodeCatalogItems: [catalogItem],
    node: { id: "n1", type: "tool_step", label: "Search", config: { query: "x" }, catalog_binding: { id: "tool:search" } },
  });
  assert.match(text(tool.root), /Required config: tool; one of a, b/);
  assert.equal(digest(tool), "abc238d0acfada81fd19e6924f72ac585730657cfdf09d2dbca40435e44ccaa3");
  const kinds = [];
  for (const type of ["agent_step", "tool_step", "trigger", "router", "supervisor", "end"]) {
    const view = await mount(path, "FlowInspector", { ...base, node: { id: `n-${type}`, type, config: {} } });
    kinds.push(digest(view));
  }
  assert.equal(digest({ toJSON: () => kinds }), "07b4d32daaf4655b9b5f0c056428a7cf8f9147551b52450a71fed1858ce3bd4c");
});

// --- Restore backup card --------------------------------------------------------------------------------------------

test("restore backup card: file preview, target, section and skill choices, the action and the job line", async () => {
  const path = "admin/components/RestoreBackupCard.tsx";
  const props = {
    projects: [{ id: "p-1", name: "Ops" }], restoreFileName: "ops.json", handleRestoreFile: async () => {}, restoreProjectId: "p-1",
    preview: { workspaceName: "Ops", formatVersion: 3, excludedSections: ["secrets", "audit_log"], sections: [
      { id: "actions", label: "Actions", included: true, count: 1 }, { id: "agents", label: "Agents", included: true, count: 4 },
      { id: "config", label: "Configuration", included: true, count: null }, { id: "skills", label: "Skills", included: false, count: 0 }] },
    setRestoreProjectId: noop, workspaceSections: [{ id: "actions", label: "Actions" }, { id: "agents", label: "Agents" }],
    restoreSections: ["actions"], toggleRestoreSection: noop, overwriteExisting: true, setOverwriteExisting: noop, restoringSkills: true,
    overwriteSkills: true, setOverwriteSkills: noop, busy: false, restorePayload: {}, restoreBackup: async () => {},
    importJob: { status: "running", rows_success: 3, rows_total: 5, rows_failed: 1 },
  };
  const full = await mount(path, "RestoreBackupCard", props);
  assert.match(text(full.root), /Never included: /);
  assert.equal(digest(full), "2e0acc7d808832a9da22d489e1b1ee62b21a2dddf7f45abac13c5a01b0e8b6c9");
  const bare = await mount(path, "RestoreBackupCard", { ...props, preview: null, importJob: null, restoringSkills: false, restoreSections: [] });
  assert.equal(digest(bare), "9ee2f9e834eb8075e39525f98f80f329bb22425d6fcee2bbf38dc6120108ca30");
});

// --- Scenario card --------------------------------------------------------------------------------------------------

test("scenario card: header, match reasons, planner and execution badges; a bare inactive profile", async () => {
  const path = "admin/components/AdminScenarioCard.tsx";
  const profile = {
    id: "s-1", project_id: "p-1", name: "Incidents", description: "", priority: 5, is_active: true,
    match_config: { route_reasons: ["summary_aggregation", "unknown_reason"] },
    planner_config: { include_skills: true, include_recent_history: true, token_budget: 4000 },
    execution_config: { required_domains: ["jira", "other_domain"], enforce_domain_coverage: true },
  };
  const props = { profile, projectNameById: new Map([["p-1", "Ops"]]), onEdit: noop, onDelete: noop };
  const full = await mount(path, "ScenarioCard", props);
  assert.match(text(full.root), /\+2 context/);
  assert.equal(digest(full), "faa95ffa365014977a32b6b03ca80152f5b790e1e964909b20c7ef4987af25ad");
  const bare = await mount(path, "ScenarioCard", { ...props, profile: { ...profile, project_id: null, is_active: false, description: "D",
    match_config: {}, planner_config: {}, execution_config: {} } });
  assert.match(text(bare.root), /any route/);
  assert.equal(digest(bare), "42b00ef5ab783eb9a797ac18008e193c3f797ec289ed0c9deaaae6a2f1a404d8");
});

// --- Flow run trace actions -----------------------------------------------------------------------------------------

test("flow run trace actions: every action's requests and state updates, on success, failure and missing input", async () => {
  const { flowRunTraceActions } = await import("../../src/admin/components/flowBuilder/flowRunTraceActions.ts");
  const log = [];
  const setter = (name) => (value) => log.push([name, typeof value === "function" ? "fn" : value]);
  const run = async (runTrace, traceInputJson, fail, action, ...args) => {
    const readJson = async (url, init) => {
      log.push(["request", url, init?.method ?? "GET", init?.body ?? null]);
      if (fail) throw new Error(`boom ${url}`);
      if (url.endsWith("/quality")) return { score: 1 };
      if (url.endsWith("/evaluate")) return { quality_summary: { score: 2 } };
      return { run: { id: "r-2" }, node_runs: [{ id: "nr-1" }] };
    };
    const actions = flowRunTraceActions({
      readJson, runTrace, traceInputJson, setError: setter("error"), setRunBusy: setter("runBusy"), setRunTrace: setter("runTrace"),
      setSelectedTraceNodeRunId: setter("nodeRun"), setOperationsOpen: setter("operations"), setQualitySummary: setter("quality"),
      setQualityBusy: setter("qualityBusy"),
    });
    log.push(["action", action]);
    await actions[action](...args);
  };
  const trace = { run: { id: "r-1" } };
  await run(trace, "{\"a\":1}", false, "resolvePausedRun", "approve", "ap-1");
  await run(trace, "{}", true, "resolvePausedRun", "reject", "ap-1");
  await run(trace, "not json", false, "resolvePausedRun", "approve", "ap-1");
  await run(trace, "{}", false, "resolvePausedRun", "approve", null);
  for (const action of ["cancelPausedRun", "recoverInterruptedRun", "loadRunQuality", "evaluateCurrentRun"]) {
    await run(trace, "{}", false, action);
    await run(trace, "{}", true, action);
    await run(null, "{}", false, action);
  }
  await run(trace, "{}", false, "loadRunQuality", "r-9");
  assert.equal(digest({ toJSON: () => log }), "a3baf5a263c7bc713ef156d79f31aab3d534a90c2cc4a0b9109f407b9f8e54d9");
});

// --- Flow palette ---------------------------------------------------------------------------------------------------

test("flow palette: collapsed, open with groups and a disabled entry, a search with matches and with none", async () => {
  const path = "admin/components/flowBuilder/FlowPalette.tsx";
  const catalog = [
    { id: "generic:router", node_type: "router", binding_type: "generic", binding_ref: "router", display_name: "Router", category: "logic",
      icon_hint: "router", description: "Branches", config_schema: {}, input_schema: {}, output_schema: {}, availability_status: "available",
      disabled_reason: null, permission_requirements: [], token_cost_risk: "low", evidence_behavior: "", audit_behavior: "", default_config: {} },
    { id: "tool:jira", node_type: "tool_step", binding_type: "tool", binding_ref: "jira_search", display_name: "Jira search", category: "tools",
      icon_hint: "jira", description: "", config_schema: {}, input_schema: {}, output_schema: {}, availability_status: "disabled",
      disabled_reason: "Connect Jira first", permission_requirements: [], token_cost_risk: "low", evidence_behavior: "", audit_behavior: "",
      default_config: {} },
  ];
  const props = { onAddNode: noop, agents: [{ id: "a-1", name: "Coder", description: "Writes code" }], nodeCatalogItems: catalog, loading: true };
  const collapsed = await mount(path, "FlowPalette", { ...props, isCollapsed: true });
  assert.equal(digest(collapsed), "b971c137206ab5e1a03f7bbfccd005f9b3642c21ab50f486f5b533550ba8746b");
  const view = await mount(path, "FlowPalette", props);
  const headers = view.root.findAll((node) => node.type === "button" && node.props.className === "flow-palette__group-header");
  for (const header of headers) await act(async () => header.props.onClick());
  assert.equal(digest(view), "8e914dddc642dd0183fd7f9943e2b3cd3ac2282ce039667c4c1c7189fd0ab3de");
  const search = view.root.findAll((node) => node.type === "input" && node.props.type === "search")[0];
  await act(async () => search.props.onChange({ target: { value: "jira" } }));
  assert.equal(digest(view), "e09b1d90ebd1b08ff3de6242d20adf52cc65d798119165a2a0dd3bdb8019a140");
  await act(async () => search.props.onChange({ target: { value: "zzz-nothing" } }));
  assert.match(text(view.root), /No step matches/);
  assert.equal(digest(view), "2a116dfc280a1b98d063f65d8ad6a18b05a74842902d1e738fd798c38286cc48");
});

// --- Phased canvas elements -----------------------------------------------------------------------------------------

test("phased canvas elements: nodes, group frames, folded groups, arrows, editing and a drag", async () => {
  const fs = await import("node:fs");
  const { buildPhasedGraph } = await import("../../src/admin/components/agentsWorkflows/canvas/phasedGraphBuild.ts");
  const { layoutPhasedGraph } = await import("../../src/admin/components/agentsWorkflows/canvas/phasedGraphLayout.ts");
  const definition = JSON.parse(fs.readFileSync(new URL("./fixtures/bugFixReproductionSeed.v1.json", import.meta.url), "utf8")).definition;
  const nodes = definition.nodes.map((raw) => ({ id: raw.id, kind: raw.type, title: raw.label, config: raw.config ?? {} }));
  const edges = definition.edges.map((raw, index) => ({ id: raw.id ?? `edge-${index + 1}`, source: raw.source_node_id,
    target: raw.target_node_id, kind: raw.kind ?? "next", when: raw.when ?? null, max_iterations: raw.max_iterations ?? null, title: raw.label ?? "" }));
  const graph = buildPhasedGraph({ nodes, edges });
  const layout = layoutPhasedGraph(graph);
  const { usePhasedCanvasElements } = (await import("./adminDigestRenderHarness.mjs")).loadModule(
    "admin/components/agentsWorkflows/canvas/usePhasedCanvasElements.ts");
  const moved = [];
  let elements;
  const Probe = (props) => {
    elements = usePhasedCanvasElements(props);
    return h("out", { json: JSON.stringify({ nodes: elements.nodes, edges: elements.edges, drawn: elements.drawn.map((box) => box.id),
      placements: [...elements.placements.keys()] }) });
  };
  const base = { graph, layout, positions: layout.positions, folded: new Set(), onFold: noop, editable: true, selectedId: null,
    onSelect: noop, onMove: (moves) => moved.push(moves), onOpenPhase: noop, editing: false, lr: false, hovered: null };
  const { default: TestRenderer } = await import("react-test-renderer");
  const render = async (props) => {
    let view;
    await act(async () => { view = TestRenderer.create(h(Probe, props)); });
    return view;
  };
  const plain = await render(base);
  assert.ok(elements.placements.size > 0);
  assert.equal(digest(plain), "98d2adf32c3544f758cf46f48e18b9d26f061123ad22a48e37bfaf9b0959e03e");
  const group = [...elements.placements.keys()][0];
  const member = graph.groups.find((item) => item.id === group).members[0];
  const edit = { selectedIds: new Set([member]), selectedEdgeId: edges[0].id, onSelectEdge: noop, onMenu: noop, onEditGroup: noop };
  const editing = await render({ ...base, folded: new Set([group]), edit, editing: true, lr: true, hovered: member, selectedId: member });
  assert.equal(digest(editing), "1637abe8353fb693b31da55233e9b485a9a33cc1dde52d6de0b741863f288069");
  elements.onDragStop([
    { id: group, position: { x: 40, y: 50 } },
    { id: "loose", position: { x: 1, y: 2 } },
    { id: member, parentId: [...elements.placements.keys()][1], position: { x: 3, y: 4 } },
  ]);
  assert.equal(digest({ toJSON: () => moved }), "08e5b5a0a8f78ab530c1ab237fdbe808b9c9ac390ac62ac46c64c9e2f9d80059");
});

// --- Engineering knowledge quality ----------------------------------------------------------------------------------

test("engineering knowledge quality: tiles, counts, scenarios and sample reports; uninstrumented misses and an error", async () => {
  const path = "admin/components/AdminEngineeringKnowledgeQualityPanel.tsx";
  const payload = (instrumented, reports) => ({
    status_counts: { published: 3, draft: 1 }, trust_counts: { high: 2 },
    usage: { retrieval_miss_count: instrumented ? 4 : null, retrieval_miss_instrumented: instrumented, retrieval_miss_note: "Not counted yet" },
    quality: { evaluated_count: 5, passed_count: 4, failed_count: 1, failures_by_gate: reports ? { evidence: 1 } : {} },
    evaluation_scenarios: [{ key: "upgrade", label: "Upgrade", required_signals: ["version", "breaking"] }],
    sample_reports: reports ? [
      { node_id: "n-1", node_key: "java.records", passed: false, status: "blocked", quality_score: 0.456, blocking_count: 1, warning_count: 2,
        blockers: [{ key: "evidence", label: "Evidence", message: "No source", severity: "block" }], warnings: [] },
      { node_id: "n-2", node_key: "java.switch", passed: true, status: "ok", quality_score: 1, blocking_count: 0, warning_count: 0, blockers: [], warnings: [] },
    ] : [],
  });
  const at = async (body, status = 200) => mount(path, "AdminEngineeringKnowledgeQualityPanel", {},
    { globals: { fetch: server(() => ({ status, body })).fetch } });
  const full = await at(payload(true, true));
  assert.match(text(full.root), /java\.records/);
  assert.equal(digest(full), "a48b8eaee12cd3deb13167f07cd92e1f7df41f7027ca35a9cbf2248bc5686e73");
  const bare = await at(payload(false, false));
  assert.match(text(bare.root), /Not counted yet/);
  assert.equal(digest(bare), "f408332bfe4a13925f81bd8182fa22ad9260e32b8f2615abcd6b3223c7c719cb");
  const failed = await at({ detail: "nope" }, 500);
  assert.equal(failed.root.findAll((node) => node.props.className === "admin-panel__error" && typeof node.type === "string").length, 1);
  assert.equal(digest(failed), "fcdf2bc572968a03b47ba8e4d8a439d5ebc8de9ac2d90d159e32a92ba1fa8cf5");
});
