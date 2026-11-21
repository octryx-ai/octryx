// Workflow designer: the canvas core. A definition opened and saved unchanged is written back unchanged (the
// shipped seeds), boxes are added with their default settings, arrows follow the backend's rules (one way out, a
// result per arrow, a way back only to an earlier box with a maximum), copy/paste gets new ids, groups are display
// only, and every change can be undone.
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

import { addNode, connect, moveNodes, removeItems, retarget, route, updateEdge, updateNode } from "../../src/admin/components/agentsWorkflows/canvas/designer/modelEditing.ts";
import { ancestors, DEFAULT_LOOP_LIMIT, freeRoutes, HISTORY_LIMIT, isBackEdge } from "../../src/admin/components/agentsWorkflows/canvas/designer/modelCore.ts";
import { chartView, fromDefinition, toDefinition } from "../../src/admin/components/agentsWorkflows/canvas/designer/modelDefinition.ts";
import { commit, redo, startHistory, undo } from "../../src/admin/components/agentsWorkflows/canvas/designer/modelHistory.ts";
import { copyItems, paste, PASTE_OFFSET } from "../../src/admin/components/agentsWorkflows/canvas/designer/modelClipboard.ts";
import { createGroup, dissolveGroup, renameGroup } from "../../src/admin/components/agentsWorkflows/canvas/designer/modelGroups.ts";
import { defaultConfig } from "../../src/admin/components/agentsWorkflows/canvas/designer/inspector/nodeDefaults.ts";

const SEEDS = JSON.parse(fs.readFileSync(
  new URL("../../../../backend/app/services/workflow_runs/seeds/phased_workflows.json", import.meta.url), "utf8",
));
const CATALOG = {
  agents: [{ key: "engineer", name: "Engineer", capability_ceiling: "deliver" }], tools: ["knowledge_search"],
  checkTypes: [{ type: "tool_called", label: "A tool was called", params: ["tools"] }], gateCheckTypes: ["tool_called"],
  workflows: [], platformActions: [{ key: "ci.status", label: "Read the CI status", routes: ["failed", "running", "succeeded"] }],
  confirmationSubjects: ["advance"], watchConditions: ["ci.failed"], outcomes: ["blocked", "done", "stopped"], deciders: ["requester"],
};
// Start → work (phase) → verify (gate) → done; the gate's "failed" goes back to work.
const SMALL = {
  execution_kind: "phased",
  budget: { max_turns: 4 },
  nodes: [
    { id: "start", type: "start", label: "Start" },
    { id: "work", type: "phase", label: "Work", config: { agent: "engineer", workflow_contract: { capability_class: "read_only" } } },
    { id: "verify", type: "gate", label: "Verify", config: { checks: [{ type: "tool_called" }] } },
    { id: "done", type: "outcome", label: "Done", config: { outcome: "done" } },
  ],
  edges: [
    { id: "e1", source_node_id: "start", target_node_id: "work" },
    { id: "e2", source_node_id: "work", target_node_id: "verify" },
    { id: "e3", source_node_id: "verify", target_node_id: "done", when: "passed" },
    { id: "rework", source_node_id: "verify", target_node_id: "work", when: "failed", kind: "loop", max_iterations: 3, label: "Rework" },
  ],
};
const small = () => fromDefinition(structuredClone(SMALL));
const edge = (model, id) => model.edges.find((item) => item.id === id);

test("the shipped seeds round-trip unchanged, with positions, groups and keys the designer does not know", () => {
  const seeds = SEEDS.filter((seed) => seed.definition);
  assert.ok(seeds.length >= 4);
  for (const seed of seeds) {
    const definition = structuredClone(seed.definition);
    assert.deepEqual(toDefinition(fromDefinition(definition)), seed.definition, seed.key);
    assert.deepEqual(definition, seed.definition, `${seed.key}: the input is not changed`);
  }
  const laidOut = {
    ...structuredClone(SMALL),
    layout: { positions: { work: { x: 10, y: 20 } }, groups: [{ id: "g", label: "Work", members: ["work", "verify"] }], zoom: 1 },
  };
  laidOut.nodes[0].extra = { kept: true };
  laidOut.edges.push({ from: "done", to: "work" });  // the old edge keys and no id
  assert.deepEqual(toDefinition(fromDefinition(laidOut)), laidOut);
  const model = fromDefinition(laidOut);
  assert.deepEqual(model.groups, [{ id: "g", label: "Work", members: ["work", "verify"] }]);
  assert.deepEqual(model.positions, { work: { x: 10, y: 20 } });
  assert.equal(edge(model, "edge-5").source, "done");
});

test("a box from the catalog gets a unique id, its kind's name and its default settings", () => {
  let model = small();
  const first = addNode(model, "phase", { x: 100.4, y: 50 });
  const second = addNode(first.model, "phase");
  assert.equal(first.id, "step-1");
  assert.equal(second.id, "step-2");
  const node = second.model.nodes.find((item) => item.id === "step-1");
  assert.deepEqual(node.config, defaultConfig("phase"));
  assert.equal(node.label, "Agent step");
  assert.deepEqual(second.model.positions["step-1"], { x: 100, y: 50 });
  model = addNode(model, "outcome").model;
  assert.equal(model.nodes.at(-1).label, "Done");
  assert.deepEqual(model.nodes.at(-1).config, { outcome: "done" });
  // The default config is a copy: changing the box never changes the next one.
  const changed = updateNode(second.model, "step-1", { label: "Fix", config: { agent: "engineer" } });
  assert.deepEqual(changed.nodes.find((item) => item.id === "step-1"), { id: "step-1", type: "phase", label: "Fix", config: { agent: "engineer" } });
  assert.deepEqual(addNode(changed, "phase").model.nodes.at(-1).config, defaultConfig("phase"));
});

test("connecting: one way out moves the arrow, several results need a 'when', an arrow back is a bounded loop", () => {
  let model = addNode(small(), "approval").model;
  // The phase has one way out: a new arrow from it moves the old one.
  let result = connect(model, "work", "approval-1", null, CATALOG);
  assert.equal(result.edgeId, "e2");
  assert.deepEqual(edge(result.model, "e2"), { id: "e2", source: "work", target: "approval-1", kind: "next", when: null, max_iterations: null });
  model = result.model;
  // The approval has two results: an arrow without one is drawn, its panel asks for which result it is taken.
  assert.deepEqual(freeRoutes(model, "approval-1", CATALOG), ["approved", "rejected"]);
  result = connect(model, "approval-1", "verify", null, CATALOG);
  assert.equal(edge(result.model, result.edgeId).when, null);
  assert.equal(connect(result.model, "approval-1", "done", null, CATALOG).edgeId, result.edgeId, "moved, not doubled");
  result = connect(model, "approval-1", "verify", "approved", CATALOG);
  assert.equal(edge(result.model, result.edgeId).when, "approved");
  assert.equal(edge(result.model, result.edgeId).kind, "next");
  model = result.model;
  assert.deepEqual(freeRoutes(model, "approval-1", CATALOG), ["rejected"]);
  // "rejected" back to work (before it): a way back with the default maximum.
  result = connect(model, "approval-1", "work", "rejected", CATALOG);
  assert.deepEqual(edge(result.model, result.edgeId), {
    id: result.edgeId, source: "approval-1", target: "work", kind: "loop", when: "rejected", max_iterations: DEFAULT_LOOP_LIMIT,
  });
  // The same result again moves its arrow instead of adding a second one.
  const again = connect(result.model, "approval-1", "verify", "rejected", CATALOG);
  assert.equal(again.edgeId, result.edgeId);
  assert.equal(again.model.edges.filter((item) => item.source === "approval-1").length, 2);
  assert.deepEqual(edge(again.model, result.edgeId).kind, "next");
  assert.equal(edge(again.model, result.edgeId).max_iterations, null);
  // An end has no way out; nothing leads into the start.
  assert.match(connect(model, "done", "work", null, CATALOG).problem, /no way out/);
  assert.match(connect(model, "work", "start", null, CATALOG).problem, /start/);
});

test("loop rules: a way back only to an earlier box (or the box itself), retargeting keeps its maximum", () => {
  const model = small();
  assert.deepEqual([...ancestors(model, "verify")].sort(), ["start", "work"]);
  assert.equal(isBackEdge(model, "verify", "work"), true);
  assert.equal(isBackEdge(model, "verify", "verify"), true);
  assert.equal(isBackEdge(model, "work", "done"), false);
  // The existing loop moved to the gate itself stays a loop with its own maximum.
  const self = retarget(model, "rework", "verify");
  assert.deepEqual([edge(self, "rework").kind, edge(self, "rework").max_iterations], ["loop", 3]);
  // Moved forward it becomes a way on and loses the maximum.
  const forward = retarget(model, "rework", "done");
  assert.deepEqual([edge(forward, "rework").kind, edge(forward, "rework").max_iterations], ["next", null]);
  const patched = updateEdge(model, "rework", { max_iterations: 5, label: undefined });
  assert.equal(edge(patched, "rework").max_iterations, 5);
  assert.equal("label" in edge(patched, "rework"), false);
  assert.equal(toDefinition(patched).edges.find((item) => item.id === "rework").label, undefined);
});

test("onRoute creates, moves and removes the arrow of one result", () => {
  let model = addNode(small(), "decision").model;
  model = route(model, "condition-1", "yes", "done");
  const created = model.edges.find((item) => item.source === "condition-1");
  assert.deepEqual([created.when, created.target, created.kind], ["yes", "done", "next"]);
  model = route(model, "condition-1", "yes", "verify");
  assert.equal(model.edges.filter((item) => item.source === "condition-1").length, 1);
  assert.equal(edge(model, created.id).target, "verify");
  model = route(model, "condition-1", "yes", null);
  assert.equal(model.edges.some((item) => item.source === "condition-1"), false);
  assert.equal(route(model, "condition-1", "no", null), model);
});

test("removing a box removes its arrows, its position and its group membership; the start stays", () => {
  let model = moveNodes(small(), [["verify", { x: 1, y: 2 }]]);
  model = createGroup(model, ["work", "verify"], "Work", []).model;
  const removed = removeItems(model, ["verify", "start"]);
  assert.deepEqual(removed.nodes.map((node) => node.id), ["start", "work", "done"]);
  assert.deepEqual(removed.edges.map((item) => item.id), ["e1"]);
  assert.equal("verify" in removed.positions, false);
  assert.deepEqual(removed.groups, [{ id: "group-1", label: "Work", members: ["work"] }]);
  assert.deepEqual(removeItems(removed, ["work"]).groups, [], "a group left empty disappears");
  assert.deepEqual(removeItems(model, [], ["e3"]).edges.map((item) => item.id), ["e1", "e2", "rework"]);
});

test("copy and paste: new ids, the settings copied (not shared), the arrows between the copied boxes, moved aside", () => {
  let model = moveNodes(small(), [["work", { x: 0, y: 100 }], ["verify", { x: 0, y: 200 }]]);
  model = updateNode(model, "verify", { config: { checks: [{ type: "tool_called" }], phase: "work" } });
  const clip = copyItems(model, ["start", "work", "verify"]);
  assert.deepEqual(clip.nodes.map((node) => node.id), ["work", "verify"], "the start is never copied");
  const { model: pasted, ids } = paste(model, clip);
  assert.deepEqual(ids, ["step-1", "check-1"]);
  const copy = pasted.nodes.find((node) => node.id === "check-1");
  assert.equal(copy.label, "Verify (copy)");
  assert.equal(copy.config.phase, "step-1", "a reference to a copied box follows the copy");
  copy.config.checks.push({ type: "other" });
  assert.equal(pasted.nodes.find((node) => node.id === "verify").config.checks.length, 1);
  const between = pasted.edges.filter((item) => ids.includes(item.source));
  assert.deepEqual(between.map((item) => [item.source, item.target, item.kind, item.when]),
    [["step-1", "check-1", "next", null], ["check-1", "step-1", "loop", "failed"]]);
  assert.ok(between.every((item) => !model.edges.some((old) => old.id === item.id)));
  assert.deepEqual(pasted.positions["step-1"], { x: PASTE_OFFSET, y: 100 + PASTE_OFFSET });
  // Pasting twice gives two more boxes, never a clash.
  assert.deepEqual(paste(pasted, clip).ids, ["step-2", "check-2"]);
  assert.equal(copyItems(model, ["start"]), null);
});

test("groups: made from a selection, renamed and dissolved by hand; the canvas's own groups are kept on the first change", () => {
  const derived = [{ id: "group:work", label: "Work", members: ["work", "verify"] }];
  let model = small();
  assert.equal(model.groups, null);
  const made = createGroup(model, ["done", "verify"], "  ", derived);
  assert.deepEqual(made.model.groups, [
    { id: "group:work", label: "Work", members: ["work"] },
    { id: "group-1", label: "Group", members: ["done", "verify"] },
  ]);
  model = renameGroup(made.model, made.id, "Finish", derived);
  assert.equal(model.groups[1].label, "Finish");
  model = dissolveGroup(model, "group:work", derived);
  assert.deepEqual(toDefinition(model).layout, { groups: [{ id: "group-1", label: "Finish", members: ["done", "verify"] }] });
  model = dissolveGroup(model, "group-1", derived);
  assert.deepEqual(toDefinition(model).layout, { groups: [] }, "every group dissolved: an empty list, not the canvas's own");
  assert.equal(createGroup(small(), ["ghost"], "x", []).id, null);
});

test("undo and redo step through the changes; typing in one field is one step; the history is bounded", () => {
  let history = startHistory(small());
  const first = history.present;
  history = commit(history, addNode(history.present, "gate").model);
  history = commit(history, updateNode(history.present, "work", { label: "W" }), "node:work", 1000);
  history = commit(history, updateNode(history.present, "work", { label: "Wo" }), "node:work", 1500);
  history = commit(history, updateNode(history.present, "work", { label: "Wor" }), "node:work", 2000);
  assert.equal(history.past.length, 2, "three keystrokes in a row are one step");
  history = undo(history);
  assert.equal(history.present.nodes.find((node) => node.id === "work").label, "Work");
  assert.equal(history.present.nodes.length, 5);
  history = undo(history);
  assert.equal(history.present, first);
  assert.equal(undo(history), history);
  history = redo(redo(history));
  assert.equal(history.present.nodes.find((node) => node.id === "work").label, "Wor");
  assert.equal(redo(history), history);
  // A new change after undo drops the redo branch.
  history = commit(undo(history), moveNodes(history.present, [["work", { x: 1, y: 1 }]]));
  assert.equal(history.future.length, 0);
  let long = startHistory(small());
  for (let n = 0; n < HISTORY_LIMIT + 20; n += 1) long = commit(long, moveNodes(long.present, [["work", { x: n, y: 0 }]]));
  assert.equal(long.past.length, HISTORY_LIMIT);
});

test("the flow chart reads the model like the editor payload", () => {
  const view = chartView(small());
  assert.deepEqual(view.nodes.find((node) => node.id === "work"), {
    id: "work", kind: "phase", title: "Work", config: SMALL.nodes[1].config, agent: "engineer",
    capability_class: "read_only", steps: 0, checks: 0, path_rules: [],
  });
  assert.deepEqual(view.edges.find((item) => item.id === "rework"), {
    id: "rework", source: "verify", target: "work", kind: "loop", when: "failed", max_iterations: 3, title: "Rework",
  });
});

test("an End the user never moved stays right of every new box", () => {
  const starter = fromDefinition({
    execution_kind: "phased",
    nodes: [{ id: "start", type: "start", label: "Start", config: {} },
      { id: "end", type: "outcome", label: "Done", config: { outcome: "done" } }],
    edges: [{ id: "e-start", source_node_id: "start", target_node_id: "end" }],
  });
  const first = addNode(starter, "phase", { x: 300, y: 100 });
  assert.ok(first.model.positions.end.x > 300, "End right of the first box");
  const second = addNode(first.model, "phase", { x: first.model.positions.end.x + 10, y: 100 });
  assert.ok(second.model.positions.end.x > second.model.positions[second.id].x, "End moves on with the next box");
  const moved = moveNodes(second.model, [["end", { x: 50, y: 400 }]]);
  const third = addNode(moved, "phase", { x: 900, y: 100 });
  assert.deepEqual(third.model.positions.end, { x: 50, y: 400 }, "an End moved by hand stays where the user put it");
  assert.ok(!("autoEnds" in toDefinition(third.model)), "the marker is never saved");
});

test("top to bottom, the End the user never moved goes below the new box", () => {
  const starter = fromDefinition({
    execution_kind: "phased",
    nodes: [{ id: "start", type: "start", label: "Start", config: {} },
      { id: "end", type: "outcome", label: "Done", config: { outcome: "done" } }],
    edges: [{ id: "e-start", source_node_id: "start", target_node_id: "end" }],
  });
  const drawn = { direction: "tb", positions: new Map([["start", { x: 0, y: 0 }], ["end", { x: 0, y: 120 }]]) };
  const added = addNode(starter, "phase", { x: 0, y: 240 }, drawn);
  assert.equal(added.model.positions.end.x, 0, "same column");
  assert.ok(added.model.positions.end.y > 240, "below the new box");
});
