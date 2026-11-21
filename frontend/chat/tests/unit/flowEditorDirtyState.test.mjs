import assert from "node:assert/strict";
import { test } from "node:test";
import { flowAuthoringState } from "../../src/admin/components/flowBuilder/flowAuthoringState.ts";
import {
  layoutNodes,
  toDefinitionEdge,
  toFlowNode,
  toRfEdge,
  toRfNode,
} from "../../src/admin/components/flowBuilder/flowCanvasMapping.ts";
import { parseJsonObject } from "../../src/admin/components/flowBuilder/flowBuilderDefinition.ts";

// Stored v3 of the judge's draft (flow 7784cd96-1fa5-4bd5-8bfc-1b7f225a2d1d), verbatim.
const STORED_V3 = `{"schema_version": "2.0", "nodes": [{"id": "input", "type": "trigger", "label": "Concurrent B", "output_schema": {"request": "string"}, "config": {"trigger_type": "manual"}, "position": {"x": 80, "y": 80}}, {"id": "output", "type": "output", "label": "Return result", "input_schema": {"request": "string"}, "position": {"x": 380, "y": 80}}], "edges": [{"source_node_id": "input", "target_node_id": "output"}]}`;
const NAME = "sales-judge-workflow-20261002-a9052069";
const VERSION_ID = "d5e2b65a-0000-4000-8000-000000000003";

function flowWith(definition) {
  return {
    id: "7784cd96-1fa5-4bd5-8bfc-1b7f225a2d1d", key: NAME, name: NAME, description: "", status: "draft",
    current_version_id: null,
    versions: [{ id: VERSION_ID, version: 3, status: "draft", definition }],
  };
}

// The editor's load path: loadFlowDetail pretty-prints version.definition into the expert JSON,
// the canvas maps it to React Flow, React Flow reports node measurements on mount, and
// handleNodesChange → syncToParent writes the canvas back (toFlowNode / toDefinitionEdge).
function loadThroughEditor(storedDefinition) {
  const loaded = parseJsonObject(JSON.stringify(storedDefinition, null, 2));
  const positions = layoutNodes(loaded.nodes);
  const rfNodes = loaded.nodes.map((node) => ({
    ...toRfNode(node, null, positions, new Map(), new Map(), {}),
    measured: { width: 240, height: 98 },
  }));
  const rfEdges = loaded.edges.map(toRfEdge);
  const synced = {
    ...loaded,
    nodes: rfNodes.map(toFlowNode),
    edges: rfEdges.filter((edge) => edge.source && edge.target).map(toDefinitionEdge),
  };
  return parseJsonObject(JSON.stringify(synced, null, 2));
}

const clone = (value) => JSON.parse(JSON.stringify(value));

test("an unedited reload of the stored v3 is clean and runnable (the naive comparison was not)", () => {
  const stored = JSON.parse(STORED_V3);
  const working = loadThroughEditor(stored);
  // Root cause reproduced: the canvas sync adds the derived edge id, so the old
  // JSON.stringify comparison reported "Unsaved changes" for an untouched draft.
  assert.notEqual(JSON.stringify(working), JSON.stringify(stored));
  assert.equal(working.edges[0].id, "input->output");
  const state = flowAuthoringState(flowWith(stored), VERSION_ID, NAME, "", working);
  assert.equal(state.dirty, false);
  assert.equal(state.runnable, true);
  assert.equal(state.publishable, true);
  // Key order alone never counts as an edit.
  const reordered = { edges: stored.edges, nodes: stored.nodes.map((node) => Object.fromEntries(Object.entries(node).reverse())), schema_version: "2.0" };
  assert.equal(flowAuthoringState(flowWith(stored), VERSION_ID, NAME, "", reordered).dirty, false);
});

test("only editor-derived values are normalised; authored extras survive the canvas round trip", () => {
  const stored = {
    schema_version: "2.0",
    metadata: { owner: "sales" },
    nodes: [
      { id: "a", type: "trigger", label: "Start", notes: "authored", output_schema: { request: "string" } },
      { id: "b", type: "output", label: "End" },
    ],
    edges: [{ from_node_id: "a", to_node_id: "b", condition: { route: "approved" }, label: "authored edge" }],
  };
  const working = loadThroughEditor(stored);
  assert.equal(working.nodes[0].notes, "authored");
  assert.deepEqual(working.edges[0].condition, { route: "approved" });
  assert.equal(working.edges[0].label, "authored edge");
  assert.equal(flowAuthoringState(flowWith(stored), VERSION_ID, NAME, "", working).dirty, false);
});

test("every real mutation of the loaded draft is dirty and blocks Run", () => {
  const stored = JSON.parse(STORED_V3);
  const base = loadThroughEditor(stored);
  const mutations = {
    label: (def) => { def.nodes[0].label = "Concurrent C"; },
    config: (def) => { def.nodes[0].config.trigger_type = "webhook"; },
    schema: (def) => { def.nodes[1].input_schema = { request: "string", ticket: "string" }; },
    "node add": (def) => {
      def.nodes.push(toFlowNode({ id: "agent-step-1", position: { x: 680, y: 80 }, data: { id: "agent-step-1", type: "agent_step", label: "Agent" } }));
    },
    "node remove": (def) => { def.nodes = def.nodes.filter((node) => node.id !== "output"); def.edges = []; },
    "edge remove": (def) => { def.edges = []; },
    "edge add": (def) => { def.edges.push({ id: "output->input", source_node_id: "output", target_node_id: "input" }); },
    "edge mapping": (def) => { def.edges[0].source_field = "request"; def.edges[0].target_field = "request"; },
    "position move": (def) => { def.nodes[1].position = { x: 412.5, y: 96 }; },
  };
  for (const [name, mutate] of Object.entries(mutations)) {
    const edited = clone(base);
    mutate(edited);
    const state = flowAuthoringState(flowWith(stored), VERSION_ID, NAME, "", edited);
    assert.equal(state.dirty, true, `${name} must be dirty`);
    assert.equal(state.runnable, false, `${name} must block Run`);
  }
  const renamed = flowAuthoringState(flowWith(stored), VERSION_ID, `${NAME}-b`, "", base);
  assert.equal(renamed.dirty, true);
});
