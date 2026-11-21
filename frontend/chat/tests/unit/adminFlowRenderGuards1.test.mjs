// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminFlowRenderGuards1.test.mjs
//
// Render guards for the flow canvas, the Flow Builder editor, the steps and phased workflow editors and the admin
// panel switch: each is rendered with representative props and its key structure is asserted, so splitting these
// components into smaller parts keeps what they draw. React Flow is replaced by a light stand-in that renders its
// props as data attributes.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { TestRenderer, act, buttons, byTestId, flush, loader, stateHook, text, windowStub, xyflow, xyflowKnown } from "./adminFlowRenderHarness.mjs";

// --- Flow canvas ---------------------------------------------------------------------------------------------------

const FLOW = {
  schema_version: "1",
  nodes: [
    { id: "start", type: "input", label: "Start", config: {}, output_schema: { text: { type: "string" } } },
    { id: "agent-a", type: "agent", label: "Writer", config: { agent_id: "a1" }, input_schema: { text: { type: "string" } } },
    { id: "done", type: "output", label: "Done", config: {} },
  ],
  edges: [{ id: "start->agent-a", source_node_id: "start", target_node_id: "agent-a" }],
};

const AGENTS = [{ id: "a1", name: "Writer agent" }];
const TOOLS = [];
const RUN_STATUSES = {};

function renderCanvas(props) {
  const load = loader({ window: windowStub() }, { "@xyflow/react": xyflow });
  const { FlowCanvas } = load("admin/components/flowBuilder/FlowCanvas.tsx");
  const { FIT_VIEW, FLOW_MIN_ZOOM } = load("admin/components/flowBuilder/flowCanvasView.ts");
  const changes = [];
  const selections = [];
  const element = (extra = {}) => createElement(FlowCanvas, {
    definition: FLOW, onChange: (definition) => changes.push(definition), onNodeSelect: (id) => selections.push(id),
    agents: AGENTS, tools: TOOLS, nodeContracts: [], nodeCatalogItems: [], nodeRunStatuses: RUN_STATUSES, selectedNodeId: null,
    ...props, ...extra,
  });
  let view;
  act(() => { view = TestRenderer.create(element()); });
  return { view, changes, selections, element, FIT_VIEW, FLOW_MIN_ZOOM };
}

test("the flow canvas draws the palette, the graph and the idle toolbar", () => {
  const { view, FIT_VIEW, FLOW_MIN_ZOOM } = renderCanvas({});
  assert.equal(JSON.stringify(FIT_VIEW), JSON.stringify({ padding: 0.2, maxZoom: 1 }));
  assert.equal(FLOW_MIN_ZOOM, 0.2);
  const root = view.root;
  assert.equal(root.findAll((node) => node.props.className === "flow-canvas").length, 1);
  const graph = byTestId(root, "rf")[0];
  assert.equal(graph.props["data-nodes"], "start,agent-a,done");
  assert.equal(graph.props["data-edges"], "start->agent-a");
  assert.equal(graph.props["data-min-zoom"], 0.2);
  assert.equal(byTestId(root, "rf-controls").length, 1);
  assert.equal(byTestId(root, "rf-minimap").length, 0, "three nodes draw no minimap");
  const toolbar = root.find((node) => node.props.className === "flow-canvas__toolbar");
  assert.equal(toolbar.props["aria-live"], "polite");
  assert.match(text(toolbar), /Select a connection or node to edit the graph\./);
  assert.deepEqual(toolbar.findAllByType("button").map(text), ["Auto-layout"]);
  act(() => view.unmount());
});

test("a selected node offers connect, duplicate, delete and auto-layout, each writing the definition", () => {
  const { view, changes, selections } = renderCanvas({ selectedNodeId: "start" });
  const toolbar = view.root.find((node) => node.props.className === "flow-canvas__toolbar");
  assert.match(text(toolbar), /Node selected: start/);
  const select = toolbar.findByType("select");
  assert.equal(select.props["aria-label"], "Connection target");
  assert.deepEqual(select.findAllByType("option").map((option) => [option.props.value, text(option)]),
    [["", "Connect to..."], ["agent-a", "Writer"], ["done", "Done"]]);
  assert.deepEqual(toolbar.findAllByType("button").map(text), ["Connect", "Duplicate", "Delete", "Auto-layout"]);
  assert.equal(toolbar.findAllByType("button")[0].props.disabled, true, "Connect waits for a target");

  act(() => select.props.onChange({ target: { value: "done" } }));
  act(() => toolbar.findAllByType("button")[0].props.onClick());
  const connected = changes.at(-1);
  assert.deepEqual(connected.edges.map((edge) => edge.id ?? `${edge.source_node_id}->${edge.target_node_id}`).length, 2);
  assert.equal(byTestId(view.root, "rf")[0].props["data-edges"], "start->agent-a,start->done");

  act(() => view.root.find((node) => node.type === "button" && text(node) === "Delete")?.props.onClick?.());
  act(() => view.update(createElement(view.root.type, view.root.props)));
  assert.ok(changes.length >= 1);
  assert.ok(selections.includes(null));
  act(() => view.unmount());
});

test("duplicating a selected node adds a copy beside it and selects it", () => {
  const { view, changes, selections } = renderCanvas({ selectedNodeId: "agent-a" });
  const duplicate = view.root.find((node) => node.type === "button" && text(node) === "Duplicate");
  act(() => duplicate.props.onClick());
  const written = changes.at(-1);
  assert.equal(written.nodes.length, 4);
  assert.equal(written.nodes[3].label, "Writer copy");
  assert.match(written.nodes[3].id, /^agent-[0-9a-f]{8}$/);
  assert.equal(selections.at(-1), written.nodes[3].id);
  act(() => view.unmount());
});

test("a flow canvas without run statuses, agents or tools settles instead of re-rendering endlessly", () => {
  // Counts the canvas's own renders through its node state hook.
  let renders = 0;
  const countedNodesState = (initial) => {
    renders += 1;
    if (renders > 50) throw new Error("render loop");
    return stateHook(initial);
  };
  const counted = new Proxy({ ...xyflowKnown, useNodesState: countedNodesState }, {
    get: (target, name) => xyflow[name] && !(name in target) ? xyflow[name] : target[name],
  });
  const load = loader({ window: windowStub() }, { "@xyflow/react": counted });
  const { FlowCanvas } = load("admin/components/flowBuilder/FlowCanvas.tsx");
  const errors = [];
  const original = console.error;
  console.error = (...args) => errors.push(args.map(String).join(" "));
  let view;
  try {
    const element = () => createElement(FlowCanvas, {
      definition: FLOW, onChange: () => {}, onNodeSelect: () => {}, selectedNodeId: null,
    });
    act(() => { view = TestRenderer.create(element()); });
    // A parent re-render with the same props must not start a render loop.
    act(() => view.update(element()));
  } catch (error) {
    if (!/render loop/.test(String(error))) throw error;
  } finally {
    console.error = original;
  }
  assert.deepEqual(errors.filter((message) => /Maximum update depth/.test(message)), []);
  assert.ok(renders <= 4, `the canvas settles after a few renders, got ${renders}`);
  assert.equal(byTestId(view.root, "rf")[0].props["data-nodes"], "start,agent-a,done");
  act(() => view.unmount());
});

// --- Flow Builder editor -------------------------------------------------------------------------------------------

const FLOW_ROW = {
  id: "f-1", key: "incident-intake", name: "Incident intake", description: "Takes incidents", status: "draft",
  versions: [{ id: "v-1", version: 3, status: "draft", definition: FLOW, validation_report: { valid: true, errors: [], warnings: [] } }],
};

async function renderFlowBuilder() {
  const load = loader({ window: windowStub("?area=workflows&flow_id=f-1") }, { "@xyflow/react": xyflow });
  const { AdminFlowBuilderTab } = load("admin/components/flowBuilder/AdminFlowBuilderTab.tsx");
  const reads = [];
  const readJson = async (url) => {
    reads.push(url);
    if (url === "/api/v1/flows/f-1") return FLOW_ROW;
    if (url.startsWith("/api/v1/flows/node-catalog")) return { items: [] };
    if (url === "/api/v1/flows/node-registry") return { nodes: [] };
    if (url.includes("test-cases")) return [];
    if (url.includes("capabilit")) return { items: [] };
    return [];
  };
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(AdminFlowBuilderTab, { projects: [{ id: "ws-1", name: "Claims" }], readJson, onExit: () => {} }));
  });
  await flush();
  await flush();
  return { view, reads };
}

test("the Flow Builder opens a deep-linked workflow in the editor with its header, hints and canvas", async () => {
  const { view, reads } = await renderFlowBuilder();
  assert.ok(reads.includes("/api/v1/flows/f-1"));
  const root = view.root;
  const builder = root.find((node) => node.props.className === "flow-builder");
  assert.match(text(builder.findByType("h2")), /^Incident intake$/);
  assert.match(text(root.find((node) => node.props.className === "admin-panel__eyebrow")), /Workflow editor/);
  assert.equal(text(root.find((node) => typeof node.props.className === "string" && node.props.className.startsWith("flow-builder__badge"))), "draft");
  const status = root.findAll((node) => node.props.role === "status" && node.type === "p").map(text);
  assert.ok(status.some((line) => /Viewing saved revision 3 \(draft\)\. Run uses this exact revision\./.test(line)), status.join(" | "));
  assert.equal(byTestId(root, "rf")[0].props["data-nodes"], "start,agent-a,done");
  const dock = root.find((node) => node.props.className === "flow-builder__dock-toggle");
  assert.equal(text(dock), "Run & results");
  assert.equal(dock.props["aria-expanded"], false);
  assert.ok(buttons(root).length > 4);
  act(() => dock.props.onClick());
  assert.equal(text(root.find((node) => node.props.className === "flow-builder__dock-toggle")), "Hide results");
  act(() => view.unmount());
});
