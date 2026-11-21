// Workflow designer D1 and D2a: a workflow that runs in phases as a flow chart. The graph model (boxes, labelled
// arrows, branches, loops and the error path as badges, groups), the deterministic layered layout, the arrow routes,
// the saved positions, the side panel's plain words (W2) and the header's state and Publish reason (W3, W4). The
// shape is the shipped "Bug fix with a reproduction test" seed, read from the backend's seed file.
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import { test } from "node:test";

import { BADGE_ROW, BOX_HEIGHT, BOX_WIDTH, GROUP_HEAD, GROUP_PAD, LAYER_GAP } from "../../src/admin/components/agentsWorkflows/canvas/phasedGraphTypes.ts";
import { boxSubtitle, edgeLabel, repeats, shortTitle } from "../../src/admin/components/agentsWorkflows/canvas/phasedGraphWords.ts";
import { buildPhasedGraph, drawnArrows } from "../../src/admin/components/agentsWorkflows/canvas/phasedGraphBuild.ts";
import { defaultDirection, layoutPhasedGraph, LR_LAYER_GAP, mergedPositions, positionsToSave } from "../../src/admin/components/agentsWorkflows/canvas/phasedGraphLayout.ts";
import { foldArrows, foldedBox, foldGraph, groupFrame } from "../../src/admin/components/agentsWorkflows/canvas/phasedGroups.ts";
import { arrowRoutes, labelPoint, loopLabelPoint, roundedPath } from "../../src/admin/components/agentsWorkflows/canvas/phasedRoutes.ts";
import {
  describeNode, summarizeTools, summarizeWritePaths,
} from "../../src/admin/components/agentsWorkflows/canvas/phasedNodeDetails.ts";
import {
  phasedLayoutPath, phasedStatusLabel, publishBlockReason,
} from "../../src/admin/components/agentsWorkflows/canvas/phasedWorkflowModel.ts";

const SEEDS = JSON.parse(fs.readFileSync(
  new URL("../../../../backend/app/services/workflow_runs/seeds/phased_workflows.json", import.meta.url), "utf8",
));

// The editor payload the backend builds (phased_editor._node_summary) for a seed definition.
function viewOf(key) {
  return viewOfDefinition(SEEDS.find((seed) => seed.key === key).definition);
}

function viewOfDefinition(definition) {
  const nodes = definition.nodes.map((raw) => {
    const config = raw.config ?? {};
    const contract = config.workflow_contract ?? {};
    const node = { id: raw.id, kind: raw.type, title: raw.label, config };
    for (const field of ["agent", "outcome", "subject", "question", "tool", "workflow_key", "conditions", "action", "output"]) {
      if (field in config) node[field] = config[field];
    }
    if (raw.type === "phase") {
      Object.assign(node, {
        capability_class: contract.capability_class, steps: (contract.source_steps ?? []).length,
        checks: (contract.checks ?? []).length, path_rules: contract.path_rules?.write ?? [],
      });
    }
    if (raw.type === "gate") node.checks = (config.checks ?? []).length;
    return node;
  });
  const edges = definition.edges.map((raw, index) => ({
    id: raw.id ?? `edge-${index + 1}`, source: raw.source_node_id, target: raw.target_node_id, kind: raw.kind ?? "next",
    when: raw.when ?? null, max_iterations: raw.max_iterations ?? null, title: raw.label ?? "",
  }));
  return { nodes, edges };
}

// The layout assertions below pin one fixed graph: the "Bug fix with a reproduction test" seed as it shipped before
// Rebuilt the bug flow (frozen in fixtures/), so a new seed version does not turn layout tests red. Every
// current seed is still drawn by the "every shipped seed" test further down.
const VIEW = viewOfDefinition(JSON.parse(fs.readFileSync(new URL("./fixtures/bugFixReproductionSeed.v1.json", import.meta.url), "utf8")).definition);
const GRAPH = buildPhasedGraph(VIEW);
const arrow = (source, target) => GRAPH.arrows.find((item) => item.source === source && item.target === target);
const box = (id) => GRAPH.boxes.find((item) => item.id === id);

test("every node is a box marked by its kind, in plain words", () => {
  assert.equal(GRAPH.boxes.length, VIEW.nodes.length);
  assert.deepEqual(
    ["start", "ticket", "reproduce", "confirm_repro", "reproduces", "independent_review", "ci", "action_failed", "done", "blocked"]
      .map((id) => [box(id).family, box(id).kindLabel]),
    [
      ["start", "Start"], ["action", "Platform action"], ["agent", "Agent phase"], ["person", "User confirms"],
      ["check", "Check"], ["agent", "Independent review"], ["wait", "Waits for"], ["person", "Paused for the requester"],
      ["end", "End"], ["end", "End"],
    ],
  );
  assert.equal(box("ticket").subtitle, "Creates the Jira issue");
  assert.equal(box("reproduce").subtitle, "engineer · 3 checks");
  assert.equal(box("ci").subtitle, "CI green or CI red");
  assert.equal(box("done").goodEnd, true);
  assert.deepEqual(GRAPH.boxes.filter((item) => item.errorPath).map((item) => item.id), ["action_failed", "blocked", "stopped"]);
});

test("A box never says twice what its title or kind already says", () => {
  // The kind line goes where the title is the kind ("Start", "Independent review").
  assert.deepEqual(["start", "independent_review", "ticket", "done"].map((id) => box(id).kindLine),
    ["", "", "Platform action", "End"]);
  // No subtitle that repeats the title, no filler ("The run starts here", "Run ends: done").
  assert.equal(box("start").subtitle, "");
  assert.equal(box("done").subtitle, "");
  assert.equal(box("independent_review").subtitle, "");
  assert.equal(box("confirm_repro").subtitle, "", "Confirms the reproduction under Confirm the reproduction");
  assert.equal(box("prepare").subtitle, "", "Prepares the working folder under Prepare the working folder");
  assert.equal(box("retry").subtitle, "Confirms the retry choice", "a line that adds something stays");
  assert.equal(repeats("Retry, change or abort", "A step failed: retry, change or abort"), true);
  assert.equal(repeats("CI green or CI red", "CI on the pushed commit", "Waits for"), false);
  const blocked = buildPhasedGraph({ nodes: [{ id: "x", kind: "outcome", title: "Parked", outcome: "waiting" }], edges: [] });
  assert.equal(blocked.boxes[0].subtitle, "Run ends: waiting");
});

test("every exit is an arrow labelled with its result; branches and the error path are separate arrows", () => {
  assert.equal(arrow("start", "ticket").label, "");
  assert.deepEqual([arrow("ticket", "branch").label, arrow("ticket", "branch").tone], ["succeeded", "success"]);
  assert.deepEqual([arrow("ticket", "action_failed").label, arrow("ticket", "action_failed").tone], ["failed", "failure"]);
  assert.deepEqual([arrow("merged", "done").label, arrow("merged", "retry").label], ["merged", "declined"]);
  assert.equal(arrow("merged", "retry").tone, "failure");
  // A bounded loop says what sends the run back and how often.
  assert.deepEqual([arrow("green", "fix").label, arrow("green", "fix").loop], ["failed → retry (max 3)", true]);
  assert.equal(arrow("confirm_repro", "reproduce").label, "changes asked → retry (max 2)");
  assert.equal(arrow("ci", "fix").label, "CI red → retry (max 2)");
  // Two exits to the same box are one arrow.
  const both = arrow("in_review", "ci");
  assert.deepEqual([both.label, both.edgeIds, both.tone], ["succeeded or failed", ["e-in-review", "e-in-review-ko"], "neutral"]);
  assert.equal(GRAPH.arrows.length, VIEW.edges.length - 1);
  assert.equal(edgeLabel({ kind: "loop", when: null, max_iterations: null }), "again → retry");
});

test("A loop is its own arrow; an exit into an end of the error path is a badge", () => {
  const labels = (id) => box(id).badges.map((badge) => badge.label);
  assert.deepEqual(labels("ticket"), [], "the pause after a failed step is a box");
  assert.deepEqual(labels("green"), []);
  assert.deepEqual(labels("confirm_repro"), ["on stopped → Stopped"]);
  assert.deepEqual(labels("ci"), []);
  assert.deepEqual(labels("retry"), ["on stopped → Blocked"]);
  // The loop is drawn: its arrow goes back to the box it repeats, with what sends the run back.
  const loop = arrow("green", "fix");
  assert.deepEqual([loop.loop, loop.badge, loop.tone, loop.label, loop.edgeIds],
    [true, false, "loop", "failed → retry (max 3)", ["loop-fix"]]);
  // An exit taken whatever the result says "then".
  assert.deepEqual(labels("action_failed"), ["then → Blocked"]);
  // Only the ends of the error path are not drawn.
  assert.deepEqual(GRAPH.boxes.filter((item) => item.offPath).map((item) => item.id), ["blocked", "stopped"]);
  const drawn = drawnArrows(GRAPH);
  assert.ok(drawn.every((item) => !item.badge));
  assert.ok(drawn.includes(loop), "the loop is among the drawn arrows");
  // A failure into a box that is not the error path stays an arrow (a declined PR's choice).
  assert.ok(drawn.includes(arrow("merged", "retry")));
  assert.equal(arrow("merged", "retry").aside, false);
});

test("A box where a person decides stays a box on the error path, its arrows thin; an end reached normally is a box", () => {
  // The pause after a failed step ("A step failed: retry, change or abort") is drawn, aside, with thin arrows.
  assert.deepEqual(GRAPH.boxes.filter((item) => item.aside).map((item) => item.id), ["action_failed"]);
  const into = drawnArrows(GRAPH).filter((item) => item.target === "action_failed");
  assert.deepEqual(into.map((item) => item.source), ["ticket", "prepare", "branch", "push", "pr"]);
  assert.ok(into.every((item) => item.aside && item.tone === "failure"));
  assert.ok(drawnArrows(GRAPH).filter((item) => item.target !== "action_failed").every((item) => !item.aside));
  // "Waiting for clarification" ends the triage after the questions were posted: a box with its arrow, not a badge.
  const triage = buildPhasedGraph(viewOf("jira-intake-triage"));
  const clarification = triage.boxes.find((item) => item.id === "clarification");
  assert.deepEqual([clarification.offPath, clarification.aside, clarification.errorPath], [false, false, false]);
  assert.deepEqual(triage.boxes.find((item) => item.id === "to_clarification").badges, []);
  assert.ok(drawnArrows(triage).some((item) => item.source === "to_clarification" && item.target === "clarification"));
  assert.deepEqual(triage.boxes.filter((item) => item.offPath).map((item) => item.id), ["stopped"]);
  // While a person edits, every box is drawn and every edge is its own arrow; loops stay badges that know their edge.
  const editing = buildPhasedGraph(VIEW, { editing: true });
  assert.equal(editing.boxes.some((item) => item.offPath), false);
  assert.equal(editing.arrows.length, VIEW.edges.length);
  assert.ok(editing.arrows.filter((item) => !item.loop).every((item) => !item.badge));
  assert.deepEqual(editing.boxes.find((item) => item.id === "merged").badges, []);
});

test("A badge names a long target briefly; its tooltip says it in full", () => {
  assert.equal(shortTitle({ title: "A step failed: retry, change or abort", kind: "pause" }), "Pause");
  assert.equal(shortTitle({ title: "Stopped", kind: "outcome" }), "Stopped");
  assert.equal(shortTitle({ title: "Approve the production deployment", kind: "approval" }), "Approve the producti…");
  const view = {
    nodes: [
      { id: "s", kind: "start", title: "Start" },
      { id: "act", kind: "platform_action", title: "Push", action: "scm.push" },
      { id: "end", kind: "outcome", title: "Blocked because the push could not be done", outcome: "blocked" },
      { id: "done", kind: "outcome", title: "Done", outcome: "done" },
    ],
    edges: [
      { id: "a", source: "s", target: "act", kind: "next", when: null, max_iterations: null, title: "" },
      { id: "b", source: "act", target: "done", kind: "next", when: "succeeded", max_iterations: null, title: "" },
      { id: "c", source: "act", target: "end", kind: "next", when: "failed", max_iterations: null, title: "" },
    ],
  };
  const [badge] = buildPhasedGraph(view).boxes.find((item) => item.id === "act").badges;
  assert.equal(badge.label, "on failure → Blocked because the…");
  assert.equal(badge.title, "on failure → Blocked because the push could not be done");
});

test("the layout runs top to bottom: the way forward is one column, a box with badges is taller", () => {
  const { positions, heights } = layoutPhasedGraph(GRAPH);
  const main = ["start", "ticket", "branch", "prepare", "reproduce", "confirm_repro", "reproduces", "fix", "green",
    "independent_review", "review", "push", "pr", "in_review", "ci", "merged", "done"];
  const column = positions.get("start").x;
  // A group's frame gets room for its header above its first box and its margin below its last.
  const opens = new Set(GRAPH.groups.map((group) => group.members[0]));
  const closes = new Set(GRAPH.groups.map((group) => group.members.at(-1)));
  for (const [index, id] of main.entries()) {
    assert.equal(positions.get(id).x, column, id);
    if (index) {
      const above = main[index - 1];
      const room = (opens.has(id) ? GROUP_HEAD : 0) + (closes.has(above) ? GROUP_PAD : 0);
      assert.equal(positions.get(id).y, positions.get(above).y + heights.get(above) + LAYER_GAP + room, `${id} below ${above}`);
    }
  }
  // "prepare" closes the Preparation group, "reproduce" opens its phase's group.
  assert.equal(positions.get("reproduce").y - positions.get("prepare").y - heights.get("prepare"), LAYER_GAP + GROUP_HEAD + GROUP_PAD);
  assert.equal(heights.get("confirm_repro"), BOX_HEIGHT + BADGE_ROW);
  assert.ok(positions.get("retry").x >= column + BOX_WIDTH, "a branch reached through a failure sits to the right");
  // The error path's boxes keep a position beside the chart (a saved layout keeps them), right of every drawn box.
  const right = Math.max(...GRAPH.boxes.filter((item) => !item.offPath && !item.aside).map((item) => positions.get(item.id).x + BOX_WIDTH));
  for (const id of ["action_failed", "blocked", "stopped"]) assert.ok(positions.get(id).x > right, id);
  // No two boxes overlap.
  const boxes = [...positions.entries()];
  for (const [i, [a, p]] of boxes.entries()) {
    for (const [b, q] of boxes.slice(i + 1)) {
      const apart = Math.abs(p.x - q.x) >= BOX_WIDTH || (p.y < q.y ? q.y - p.y >= heights.get(a) : p.y - q.y >= heights.get(b));
      assert.ok(apart, `${a} and ${b} overlap`);
    }
  }
});

test("the layout is deterministic", () => {
  const first = layoutPhasedGraph(buildPhasedGraph(VIEW));
  const second = layoutPhasedGraph(buildPhasedGraph(structuredClone(VIEW)));
  assert.deepEqual([...first.positions], [...second.positions]);
  assert.deepEqual([...first.routes], [...second.routes]);
  for (const key of SEEDS.filter((seed) => seed.definition).map((seed) => seed.key)) {
    const graph = buildPhasedGraph(viewOf(key));
    assert.deepEqual([...layoutPhasedGraph(graph).positions], [...layoutPhasedGraph(graph).positions], key);
  }
});

test("the layout of every seed, both directions and folded, stays exactly as it is", () => {
  const lines = [];
  for (const key of SEEDS.filter((seed) => seed.definition).map((seed) => seed.key)) {
    const graph = buildPhasedGraph(viewOf(key));
    const folded = foldGraph(graph, new Set(graph.groups.map((group) => group.id)));
    for (const [name, shape] of [["open", graph], ["folded", folded]]) {
      for (const direction of ["tb", "lr"]) {
        const layout = layoutPhasedGraph(shape, direction);
        lines.push(JSON.stringify([key, name, direction, [...layout.positions], [...layout.routes], [...layout.heights], layout.layers]));
      }
    }
  }
  assert.ok(lines.length >= 8);
  const digest = crypto.createHash("sha256").update(lines.join("\n")).digest("hex");
  assert.equal(digest, "b18558ad785d7322d8205d0f059d94bd35aec57b9c339bd7f79ffcb93007ed41");
});

test("arrows: a failure branch leaves sideways, a loop goes back up the side, the error path draws no line", () => {
  const layout = layoutPhasedGraph(GRAPH);
  const routes = arrowRoutes(GRAPH.arrows, layout.positions, layout);
  // A loop leaves the source's right side, runs up a lane right of every box it passes and enters the target's side.
  const back = routes.get(arrow("green", "fix").id);
  const greenAt = layout.positions.get("green");
  const fixAt = layout.positions.get("fix");
  assert.deepEqual(back[0], { x: greenAt.x + BOX_WIDTH, y: greenAt.y + BOX_HEIGHT / 2 });
  assert.deepEqual(back.at(-1), { x: fixAt.x + BOX_WIDTH, y: fixAt.y + BOX_HEIGHT / 2 });
  const passed = [...layout.positions].filter(([, point]) => point.y < greenAt.y + layout.heights.get("green") && point.y + BOX_HEIGHT > fixAt.y);
  assert.ok(back[1].x > Math.max(...passed.map(([, point]) => point.x + BOX_WIDTH)), "the lane runs right of every box it passes");
  const lanes = [arrow("green", "fix"), arrow("ci", "fix"), arrow("confirm_repro", "reproduce")].map((item) => routes.get(item.id)[1].x);
  assert.equal(new Set(lanes).size, lanes.length, "each loop has its own lane");
  assert.equal(routes.has(arrow("confirm_repro", "stopped").id), false, "an end of the error path is a badge");
  assert.ok(routes.has(arrow("ticket", "action_failed").id), "the pause is a box: its thin arrow has a route");
  assert.equal(routes.size, drawnArrows(GRAPH).length);

  const merged = layout.positions.get("merged");
  const declined = routes.get(arrow("merged", "retry").id);
  assert.deepEqual(declined[0], { x: merged.x + BOX_WIDTH, y: merged.y + BOX_HEIGHT / 2 });
  assert.equal(declined[1].y, declined[0].y);
  const retry = layout.positions.get("retry");
  assert.deepEqual(declined.at(-1), { x: retry.x + BOX_WIDTH / 2, y: retry.y });
  // An arrow leaves from under the box's badges.
  const confirm = layout.positions.get("confirm_repro");
  assert.deepEqual(routes.get(arrow("confirm_repro", "reproduces").id)[0],
    { x: confirm.x + BOX_WIDTH / 2, y: confirm.y + BOX_HEIGHT + BADGE_ROW });

  const moved = new Map(layout.positions).set("retry", { x: -600, y: retry.y });
  const plain = arrowRoutes(GRAPH.arrows, moved, layout).get(arrow("merged", "retry").id);
  assert.deepEqual(plain[0], { x: merged.x + BOX_WIDTH / 2, y: merged.y + BOX_HEIGHT });
  assert.ok(plain.every((point, index) => !index || point.x === plain[index - 1].x || point.y === plain[index - 1].y));
  assert.match(roundedPath(declined), /^M [-\d.]+ [-\d.]+ L/);
  const at = labelPoint(declined);
  assert.equal(at.y, declined[0].y);
});

test("A phase and its checks form a group that folds into one box without moving any box", () => {
  assert.deepEqual(GRAPH.groups.map((group) => [group.id, group.members]), [
    ["steps:ticket", ["ticket", "branch", "prepare"]],
    ["group:reproduce", ["reproduce", "confirm_repro", "reproduces"]],
    ["group:fix", ["fix", "green"]],
    ["group:independent_review", ["independent_review", "review"]],
    ["steps:push", ["push", "pr", "in_review", "ci"]],
  ]);
  const phases = GRAPH.groups.filter((group) => group.kind === "phase");
  const layout = layoutPhasedGraph(GRAPH);
  const { positions, heights } = layout;
  // The frame encloses its boxes with the header above.
  const frame = groupFrame(["fix", "green"], positions, heights);
  const fix = positions.get("fix");
  const green = positions.get("green");
  assert.deepEqual(frame, {
    x: fix.x - GROUP_PAD, y: fix.y - GROUP_HEAD, width: BOX_WIDTH + 2 * GROUP_PAD,
    height: green.y + heights.get("green") - fix.y + GROUP_HEAD + GROUP_PAD,
  });
  // Folded: one box with the phase's title, the others' titles and what leads out; a loop inside it "repeats".
  const folded = foldedBox(phases[0], GRAPH);
  assert.deepEqual([folded.id, folded.kindLine, folded.title, folded.subtitle],
    ["group:reproduce", "Group · 3 boxes", "Reproduce", "Confirm the reproduction · Reproduces"]);
  assert.deepEqual(folded.badges.map((badge) => badge.label), ["↻ repeats (max 2)", "on stopped → Stopped"]);
  assert.deepEqual(foldedBox(phases[2], GRAPH).badges.map((badge) => badge.label), [],
    "a loop out of the group stays a drawn arrow");
  // Arrows end at the folded group's box; the ones inside disappear.
  const all = new Set(phases.map((group) => group.id));
  const arrows = foldArrows(drawnArrows(GRAPH), phases, all);
  assert.deepEqual(arrows.filter((item) => !item.loop && (item.source.startsWith("group:") || item.target.startsWith("group:")))
    .map((item) => `${item.source}->${item.target}`),
  ["prepare->group:reproduce", "group:reproduce->group:fix", "group:fix->group:independent_review", "group:independent_review->push"]);
  // Loops into a folded group end at its box too; the ones inside it disappear (the box says "repeats").
  assert.deepEqual(arrows.filter((item) => item.loop).map((item) => `${item.source}->${item.target}`),
    ["group:independent_review->group:fix", "retry->group:fix", "retry->group:reproduce", "ci->group:fix"]);
  const drawn = drawnArrows(GRAPH);
  assert.equal(foldArrows(drawn, GRAPH.groups, new Set()), drawn, "nothing folded, nothing changes");
  // Folding is a view: hand-placed positions stay exactly as they are and nothing new is saved.
  const placed = new Map(positions).set("green", { x: 500, y: green.y });
  assert.deepEqual(positionsToSave(placed, positions).green, { x: 500, y: green.y });
  assert.deepEqual(groupFrame(["fix", "green"], placed, heights).width, 500 + BOX_WIDTH - fix.x + 2 * GROUP_PAD);
  // Only checks and confirmations right after a phase join it; a branch point ends the group.
  const triage = buildPhasedGraph(viewOf("jira-intake-triage"));
  assert.deepEqual(triage.groups.filter((group) => group.kind === "phase").map((group) => group.members), [["understand", "ready_gate"]]);
});

test("Platform steps one after the other form a group; a step with its own branching stays a box", () => {
  const steps = GRAPH.groups.filter((group) => group.kind === "steps");
  assert.deepEqual(steps.map((group) => [group.title, group.members.length]), [["Preparation", 3], ["Wrap-up", 4]]);
  assert.deepEqual([foldedBox(steps[0], GRAPH).kindLine, foldedBox(steps[0], GRAPH).title], ["Group · 3 steps", "Preparation"]);
  // "Merged" branches (merged or declined): it is not part of the wrap-up.
  assert.equal(steps.some((group) => group.members.includes("merged")), false);
  // Folded, the bug fix is no longer a long column.
  const folded = foldGraph(GRAPH, new Set(GRAPH.groups.map((group) => group.id)));
  const drawn = folded.boxes.filter((item) => !item.offPath && !item.aside);
  assert.ok(drawn.length <= 10, `${drawn.length} boxes when folded`);
  const triage = buildPhasedGraph(viewOf("jira-intake-triage"));
  assert.deepEqual(triage.groups.filter((group) => group.kind === "steps").map((group) => group.members), [["ask", "to_clarification"]]);
});

test("Folding re-lays the chart out, so a folded group leaves no hole", () => {
  const open = layoutPhasedGraph(GRAPH);
  const all = new Set(GRAPH.groups.map((group) => group.id));
  const folded = layoutPhasedGraph(foldGraph(GRAPH, all));
  const bottom = (layout) => Math.max(...[...layout.positions].filter(([id]) => !["action_failed", "blocked", "stopped"].includes(id))
    .map(([id, point]) => point.y + layout.heights.get(id)));
  assert.ok(bottom(folded) < bottom(open) / 2, `${bottom(folded)} vs ${bottom(open)}`);
  assert.ok(folded.positions.has("group:fix") && !folded.positions.has("fix"));
  assert.equal(foldGraph(GRAPH, new Set()), GRAPH);
});

test("A long workflow is drawn left to right by default, a saved choice wins", () => {
  const top = layoutPhasedGraph(GRAPH);
  assert.equal(defaultDirection(undefined, top.layers), "tb", `${top.layers} boxes one after the other still read top to bottom`);
  assert.equal(defaultDirection("lr", top.layers), "lr", "a saved choice wins");
  assert.equal(defaultDirection("tb", top.layers), "tb");
  assert.equal(defaultDirection(undefined, 4), "tb");
  const wide = layoutPhasedGraph(GRAPH, "lr");
  assert.equal(wide.direction, "lr");
  // The way forward is one row now, each box right of the one before.
  const main = ["start", "ticket", "branch", "prepare", "reproduce"];
  for (const [index, id] of main.entries()) {
    assert.equal(wide.positions.get(id).y, wide.positions.get("start").y, id);
    if (index) assert.equal(wide.positions.get(id).x - wide.positions.get(main[index - 1]).x, BOX_WIDTH + LR_LAYER_GAP);
  }
  // An arrow leaves a box on its right and enters the next on its left.
  const routes = arrowRoutes(drawnArrows(GRAPH), wide.positions, wide);
  const first = routes.get(arrow("start", "ticket").id);
  assert.deepEqual(first[0], { x: wide.positions.get("start").x + BOX_WIDTH, y: wide.positions.get("start").y + BOX_HEIGHT / 2 });
  assert.deepEqual(first.at(-1), { x: wide.positions.get("ticket").x, y: wide.positions.get("ticket").y + BOX_HEIGHT / 2 });
});

test("dragged boxes are saved all together, an untouched layout saves nothing", () => {
  const { positions } = layoutPhasedGraph(GRAPH);
  assert.deepEqual(positionsToSave(positions, positions), {});
  const moved = new Map(positions).set("fix", { x: 412.34, y: 900 });
  const saved = positionsToSave(moved, positions);
  assert.equal(Object.keys(saved).length, positions.size);
  assert.deepEqual(saved.fix, { x: 412.3, y: 900 });
  const merged = mergedPositions(positions, { fix: { x: 10, y: 20 }, gone: { x: 1, y: 1 }, done: { x: "a", y: 1 } });
  assert.deepEqual(merged.get("fix"), { x: 10, y: 20 });
  assert.equal(merged.has("gone"), false);
  assert.deepEqual(merged.get("done"), positions.get("done"));
  assert.equal(phasedLayoutPath("f 1"), "/api/v1/phased-workflows/f%201/layout");
});

test("Allowed paths and tools are summarised in words", () => {
  const reproduce = VIEW.nodes.find((node) => node.id === "reproduce");
  assert.equal(summarizeWritePaths(reproduce.path_rules), "Writes only test files");
  assert.equal(summarizeWritePaths(["docs/**", "**/*.md", "README*"]), "Writes only documentation");
  assert.equal(summarizeWritePaths(["tests/**", "docs/**"]), "Writes only test files and documentation");
  assert.equal(summarizeWritePaths(["src/api/**"]), "Writes only in src/api/**");
  assert.equal(summarizeWritePaths(["a/**", "b/**", "c/**", "d/**", "e/**"]), "Writes only in a/**, b/**, c/** and 2 more places");
  assert.equal(summarizeWritePaths([]), "");
  assert.equal(summarizeTools(["read_workspace_file", "code_search", "run_test_suite", "submit_reproduction", "mystery"]),
    "Can read the code, run the tests, submit the reproduction and 1 other tool (5 tools)");

  const details = describeNode(reproduce, VIEW.edges, VIEW.nodes);
  assert.equal(details.who, "The engineer agent");
  assert.match(details.what, /^Read the reported bug/);
  assert.deepEqual(details.rules.slice(0, 2), ["Change: may change files in the working folder", "Writes only test files"]);
  assert.match(details.rules[2], /^Can read the code, edit files, run the tests/);
  assert.deepEqual(details.checks.map((check) => check.label), [
    "The test suite ran", "The reproduction was submitted", "The declared lint command passes for the run change",
  ]);
  assert.deepEqual(details.exits, [{ label: "then", target: "Confirm the reproduction", tone: "neutral", loop: false }]);
  assert.equal(details.loopsIn.length, 3);
  assert.match(details.loopsIn[0], /back from Confirm the reproduction when changes asked, at most 2 times/);
  assert.ok(details.raw.workflow_contract.path_rules.write.includes("tests/**"));

  const fix = describeNode(VIEW.nodes.find((node) => node.id === "fix"), VIEW.edges, VIEW.nodes);
  assert.ok(fix.rules.includes("Must keep the confirmed tests as they are"));
  const ticket = describeNode(VIEW.nodes.find((node) => node.id === "ticket"), VIEW.edges, VIEW.nodes);
  assert.deepEqual([ticket.who, ticket.what], ["The platform (no agent)", "Creates the Jira issue."]);
  assert.deepEqual(ticket.exits.map((exit) => [exit.label, exit.target, exit.tone]), [
    ["succeeded", "Bugfix branch", "success"], ["failed", "A step failed: retry, change or abort", "failure"],
  ]);
});

test("The version state is said once", () => {
  const published = { version: 8, version_status: "published", published_version: 8 };
  assert.equal(phasedStatusLabel(published), "Published v8");
  assert.doesNotMatch(phasedStatusLabel(published), /published v8.*published v8/i);
  assert.equal(phasedStatusLabel({ version: 9, version_status: "draft", published_version: 8 }), "Draft v9 · published v8");
  assert.equal(phasedStatusLabel({ version: 1, version_status: "draft", published_version: null }), "Draft v1 · not published yet");
});

test("A disabled Publish says why", () => {
  const ok = { valid: true, errors: [], warnings: [] };
  const draft = { editable: true, version: 9, version_status: "draft", validation_report: ok };
  assert.equal(publishBlockReason(draft), "");
  assert.equal(publishBlockReason({ ...draft, version: 8, version_status: "published" }), "No draft changes: v8 is already published.");
  assert.equal(publishBlockReason({ ...draft, editable: false }), "Archived workflows cannot be published.");
  assert.equal(publishBlockReason(draft, { unsavedLayout: true }), "Save or undo the moved boxes first.");
  const broken = { valid: false, errors: [{ code: "a", message: "A" }, { code: "b", message: "B" }], warnings: [] };
  assert.equal(publishBlockReason({ ...draft, validation_report: broken }), "Fix the 2 problems listed above first.");
  assert.equal(publishBlockReason({ ...draft, validation_report: { ...broken, errors: broken.errors.slice(1) } }),
    "Fix the problem listed above first.");
});

test("a loop's label sits on the middle of its lane, not beside the box", () => {
  const layout = layoutPhasedGraph(GRAPH);
  const routes = arrowRoutes(GRAPH.arrows, layout.positions, layout);
  const loop = arrow("green", "fix");
  const corners = routes.get(loop.id);
  assert.deepEqual(loopLabelPoint(loop, corners), { x: corners[1].x, y: (corners[1].y + corners[2].y) / 2 });
  assert.equal(loopLabelPoint(arrow("merged", "retry"), routes.get(arrow("merged", "retry").id)), null, "only loops");
});

test("a phase's subtitle names its own model when it sets one", () => {
  const phase = { id: "backend", kind: "phase", title: "Backend developer", agent: "engineer", checks: 1 };
  assert.equal(boxSubtitle(phase), "engineer · 1 check");
  assert.equal(boxSubtitle({ ...phase, config: { model: "claude-sonnet-5-5" } }), "engineer · Claude Sonnet 5.5 · 1 check");
  assert.equal(boxSubtitle({ ...phase, config: { model: "  " } }), "engineer · 1 check");
});

test("every shipped seed is drawn whole: one box per node, one arrow per edge between its boxes", () => {
  for (const key of SEEDS.filter((seed) => seed.definition).map((seed) => seed.key)) {
    const view = viewOf(key);
    const graph = buildPhasedGraph(view);
    assert.equal(graph.boxes.length, view.nodes.length, key);
    for (const edge of view.edges) {
      assert.ok(graph.arrows.some((item) => item.source === edge.source && item.target === edge.target),
        `${key}: ${edge.source} -> ${edge.target}`);
    }
  }
});
