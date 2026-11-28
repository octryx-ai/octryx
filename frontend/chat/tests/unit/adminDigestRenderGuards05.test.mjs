// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards05.test.mjs
//
// Render guards for admin panels, cards and inspectors whose long functions are split into smaller parts: each renders
// with representative props, keeps its key labels and test ids, and keeps its whole rendered tree (a digest of the
// test renderer's JSON), so the split draws exactly what the original drew.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement as h } from "react";
import { act, digest, mount, noop, server, text } from "./adminDigestRenderHarness.mjs";

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
