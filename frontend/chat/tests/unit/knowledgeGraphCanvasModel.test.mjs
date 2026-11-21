// Knowledge › Explore › Graph redesign: the clustered layout never overlaps circles, keeps types
// together and is stable; type colours survive a legend filter; labels go to the focus and the hubs first; the
// focus neighbourhood, edge looks and the "N of M" count line; the breadcrumb trail.
import assert from "node:assert/strict";
import { test } from "node:test";
import { egoLayout, layoutGraph, nodeRadius } from "../../src/admin/components/entityGraph/kgLayout.ts";
import {
  assignTypeSlots, countLine, edgeLabels, withTypes, edgeLook, placeEdgeLabels, labelOrder, legendItems, neighbourhood, onlyType, showsEdgeLabel, toggleType,
} from "../../src/admin/components/entityGraph/kgView.ts";
import { crumbLabel, cutTrail } from "../../src/admin/components/entityGraph/entityGraphFocusTrail.ts";
import { placeLabels } from "../../src/admin/components/entityGraph/entityGraphLabels.ts";
import { currentIdsParam, mergeAdditions, placeAround } from "../../src/admin/components/entityGraph/kgExpand.ts";
import { graphExpandUrl } from "../../src/admin/components/entityGraph/entityGraphPresentation.ts";

// A fraud-platform-like graph: hubs (teams, services) and many leaves (rules, merchants, incidents).
function sample() {
  const nodes = [];
  const edges = [];
  const add = (type, count) => Array.from({ length: count }, (_, i) => {
    const node = { id: `${type}-${i}`, node_type: type, degree: 0 };
    nodes.push(node);
    return node;
  });
  const teams = add("Team", 6);
  const services = add("Service", 20);
  const rules = add("Rule", 60);
  const merchants = add("Merchant", 40);
  const link = (a, b) => { edges.push({ id: `e${edges.length}`, source: a.id, target: b.id }); a.degree += 1; b.degree += 1; };
  rules.forEach((rule, i) => { link(rule, services[i % 3]); link(rule, teams[i % 2]); link(rule, merchants[i % merchants.length]); });
  services.forEach((service, i) => { link(service, teams[i % teams.length]); if (i) link(service, services[i - 1]); });
  return { nodes, edges };
}

test("no two circles overlap, and each type stays in its own cluster", () => {
  const { nodes, edges } = sample();
  const layout = layoutGraph(nodes, edges);
  const placed = nodes.map((node) => ({ node, at: layout.nodes.get(node.id) }));
  assert.equal(placed.filter(({ at }) => !at).length, 0, "every entity is placed");
  for (let i = 0; i < placed.length; i += 1) {
    for (let j = i + 1; j < placed.length; j += 1) {
      const a = placed[i].at;
      const b = placed[j].at;
      assert.ok(Math.hypot(a.x - b.x, a.y - b.y) >= a.r + b.r, `${placed[i].node.id} overlaps ${placed[j].node.id}`);
    }
  }
  // Clusters are disjoint discs and every entity lies inside its own type's disc.
  for (const { node, at } of placed) {
    const own = layout.clusters.find((cluster) => cluster.type === node.node_type);
    assert.ok(Math.hypot(at.x - own.x, at.y - own.y) <= own.r + 0.01, `${node.id} left its cluster`);
  }
  for (let i = 0; i < layout.clusters.length; i += 1) {
    for (let j = i + 1; j < layout.clusters.length; j += 1) {
      const a = layout.clusters[i];
      const b = layout.clusters[j];
      assert.ok(Math.hypot(a.x - b.x, a.y - b.y) >= a.r + b.r, `${a.type} and ${b.type} clusters overlap`);
    }
  }
});

test("the hub of a type sits in the middle of its cluster, and the same input gives the same picture", () => {
  const { nodes, edges } = sample();
  const first = layoutGraph(nodes, edges);
  const again = layoutGraph(nodes.map((node) => ({ ...node })), edges.map((edge) => ({ ...edge })));
  assert.deepEqual([...again.nodes.entries()], [...first.nodes.entries()]);
  const teams = nodes.filter((node) => node.node_type === "Team").sort((a, b) => b.degree - a.degree);
  const cluster = first.clusters.find((entry) => entry.type === "Team");
  const hub = first.nodes.get(teams[0].id);
  assert.equal(hub.hub, true);
  assert.deepEqual([hub.x, hub.y], [cluster.x, cluster.y]);
  assert.ok(hub.r > first.nodes.get(teams.at(-1).id).r || teams[0].degree === teams.at(-1).degree);
  assert.ok(nodeRadius(400) <= 24 && nodeRadius(0) === 7);
});

test("an empty graph and a single entity lay out without error", () => {
  assert.equal(layoutGraph([], []).nodes.size, 0);
  const one = layoutGraph([{ id: "a", node_type: "System", degree: 0 }], []);
  assert.deepEqual([one.nodes.get("a").x, one.nodes.get("a").y], [0, 0]);
});

test("the phone's neighbourhood puts the entity in the middle and its neighbours around it, apart", () => {
  const centre = { id: "c", node_type: "Team", degree: 30 };
  const around = Array.from({ length: 30 }, (_, i) => ({ id: `n${i}`, node_type: i % 2 ? "Rule" : "Service", degree: 1 }));
  const placed = egoLayout(centre, around);
  assert.deepEqual([placed.get("c").x, placed.get("c").y], [0, 0]);
  const points = [...placed.values()];
  for (let i = 0; i < points.length; i += 1) {
    for (let j = i + 1; j < points.length; j += 1) {
      assert.ok(Math.hypot(points[i].x - points[j].x, points[i].y - points[j].y) >= points[i].r + points[j].r);
    }
  }
});

test("each type gets its own colour; hiding a type in the legend repaints nobody; types beyond eight are 'other'", () => {
  const types = { Rule: 90, Merchant: 60, Incident: 45, Service: 30, Team: 10, Model: 12, System: 12, Dataset: 15, Change: 7, Cluster: 2 };
  const slots = assignTypeSlots(types);
  const coloured = [...slots.values()].filter((slot) => slot > 0);
  assert.equal(new Set(coloured).size, 8, "eight distinct colours");
  assert.equal(slots.get("Cluster"), 0, "the least frequent types share the neutral colour");
  // The legend works on the loaded view, so the colour assignment does not see what is hidden.
  const nodes = [{ node_type: "Rule" }, { node_type: "Rule" }, { node_type: "Team" }];
  const legend = legendItems(nodes, new Set(["Rule"]), slots);
  assert.deepEqual(legend.map((item) => [item.type, item.total, item.shown, item.hidden, item.slot]),
    [["Rule", 2, 0, true, slots.get("Rule")], ["Team", 1, 1, false, slots.get("Team")]]);
});

test("the legend filter: a click toggles one type, 'only' shows one type alone and again shows all", () => {
  const all = ["Rule", "Team", "Service"];
  assert.deepEqual([...toggleType(new Set(), "Rule")], ["Rule"]);
  assert.deepEqual([...toggleType(new Set(["Rule"]), "Rule")], []);
  const alone = onlyType(new Set(), "Team", all);
  assert.deepEqual([...alone].sort(), ["Rule", "Service"]);
  assert.deepEqual([...onlyType(alone, "Team", all)], []);
});

test("labels go to the selection, the hovered entity, neighbours, matches and hubs before the rest", () => {
  const candidates = [
    { id: "leaf", degree: 1, hub: false, name: "Leaf" },
    { id: "big", degree: 40, hub: false, name: "Big" },
    { id: "hub", degree: 5, hub: true, name: "Hub" },
    { id: "match", degree: 1, hub: false, name: "Match" },
    { id: "near", degree: 1, hub: false, name: "Near" },
    { id: "hover", degree: 1, hub: false, name: "Hover" },
    { id: "sel", degree: 1, hub: false, name: "Sel" },
  ];
  assert.deepEqual(labelOrder(candidates, { selectedId: "sel", hoverId: "hover", neighbours: new Set(["near"]), matches: new Set(["match"]) }),
    ["sel", "hover", "near", "match", "hub", "big", "leaf"]);
  // Zooming in (a smaller font in canvas units) frees space, so more labels fit without colliding.
  const row = Array.from({ length: 10 }, (_, i) => ({ id: `n${i}`, x: i * 60, y: 0, radius: 6, display_name: `Entity number ${i}` }));
  const order = row.map((node) => node.id);
  const far = placeLabels(row, order, 12 / 0.5).size;
  const near = placeLabels(row, order, 12 / 2).size;
  assert.ok(near > far, `zoomed in ${near} labels, zoomed out ${far}`);
});

test("focus: the neighbourhood is one relationship deep; edges are quiet, highlighted at the selection, faded elsewhere", () => {
  const edges = [{ id: "1", source: "a", target: "b" }, { id: "2", source: "c", target: "a" }, { id: "3", source: "c", target: "d" }];
  assert.deepEqual([...neighbourhood("a", edges)].sort(), ["a", "b", "c"]);
  assert.equal(neighbourhood("", edges).size, 0);
  assert.equal(edgeLook(edges[0], ""), "idle");
  assert.equal(edgeLook(edges[0], "a"), "focus");
  assert.equal(edgeLook(edges[2], "a"), "dim");
  assert.equal(edgeLook(edges[2], "a", "3"), "hover");
  assert.equal(showsEdgeLabel("focus", 5), true);
  assert.equal(showsEdgeLabel("focus", 40), false, "too many relationships to label: hover shows them");
  assert.equal(showsEdgeLabel("idle", 1), false);
});

test("the count line says how many of the loaded entities are drawn", () => {
  assert.equal(countLine({ shown: 128, loaded: 150, relationships: 212 }), "128 of 150 entities · 212 relationships");
  assert.equal(countLine({ shown: 1, loaded: 1, relationships: 1 }), "1 entity · 1 relationship");
  // With the server's totals the counts are of the whole visible graph.
  assert.equal(countLine({ shown: 128, loaded: 150, relationships: 212, totalNodes: 409, totalEdges: 915 }),
    "128 of 409 entities · 212 of 915 relationships");
  assert.equal(countLine({ shown: 9, loaded: 9, relationships: 9, totalNodes: 9, totalEdges: 9 }), "9 entities · 9 relationships");
});

test("breadcrumbs: short names per context, and a crumb restores its context and drops the later ones", () => {
  const start = { query: "", focusNodeId: "", focusName: "", selectedId: "" };
  const search = { query: "card", focusNodeId: "", focusName: "", selectedId: "x" };
  const focus = { query: "", focusNodeId: "n1", focusName: "score-api", selectedId: "" };
  assert.deepEqual([start, search, focus].map(crumbLabel), ["All entities", "“card”", "score-api"]);
  const back = cutTrail([start, search, focus], 1);
  assert.deepEqual(back, { previous: search, trail: [start] });
  assert.equal(cutTrail([start], 3), null);
});

test("two relationships between the same two entities share one label instead of stacking two", () => {
  const labels = edgeLabels([
    { id: "1", source: "a", target: "b", relation: "inconsistent across", labelled: true },
    { id: "2", source: "b", target: "a", relation: "inconsistent across", labelled: true },
    { id: "3", source: "a", target: "b", relation: "depends on", labelled: true },
    { id: "4", source: "a", target: "c", relation: "owned by", labelled: false },
  ]);
  assert.deepEqual([...labels], [["1", "inconsistent across · depends on"]]);
});

test("relationship labels sit mid-edge clear of circles and of each other; a too-short edge keeps its label for hover", () => {
  const spots = [
    { id: "a", x1: 0, y1: 0, x2: 200, y2: 0, text: "owned by" },
    { id: "b", x1: 0, y1: 4, x2: 200, y2: 4, text: "depends on" },
    { id: "c", x1: 0, y1: 0, x2: 0, y2: 200, text: "part of" },
    { id: "short", x1: 300, y1: 0, x2: 340, y2: 0, text: "inconsistent across" },
  ];
  const placed = placeEdgeLabels(spots, 1);
  assert.deepEqual([...placed.keys()], ["a", "c"], "b would sit on a; the short edge cannot hold its label");
  assert.deepEqual([placed.get("a").x, placed.get("a").y], [100, 0], "on the middle of the edge");
  // A circle next to the middle keeps the label away.
  assert.equal(placeEdgeLabels([spots[0]], 1, [{ x: 100, y: 14, r: 8 }]).size, 0);
  // Zoomed in, the same labels take less canvas space: the short edge now holds its label.
  assert.ok(placeEdgeLabels(spots, 4).has("short"));
});

test("additive Expand: the ids the view shows fit the server's limit, the most important first", () => {
  const all = Array.from({ length: 300 }, (_, i) => `id${String(i).padStart(61, "0")}`);
  const param = currentIdsParam(all, ["sel", all[299], all[298]], 12000);
  assert.ok(param.length <= 12000);
  assert.deepEqual(param.split(",").slice(0, 3), ["sel", all[299], all[298]], "selection, the entity, its neighbours first");
  assert.equal(new Set(param.split(",")).size, param.split(",").length, "no id twice");
  assert.equal(currentIdsParam(["a", "b"], ["b"]), "b,a");
});

test("additive Expand: new entities ring the expanded one without touching anything drawn; nothing old moves", () => {
  const occupied = [{ x: 0, y: 0, r: 20 }, { x: 120, y: 0, r: 10 }, { x: 0, y: -110, r: 10 }];
  const items = Array.from({ length: 25 }, (_, i) => ({ id: `n${i}`, node_type: i % 2 ? "Rule" : "Team", degree: 1 }));
  const placed = placeAround({ x: 0, y: 0, r: 20 }, items, occupied);
  assert.equal(placed.size, 25);
  const circles = occupied.concat(Array.from(placed.values()));
  for (let i = 0; i < circles.length; i += 1) {
    for (let j = i + 1; j < circles.length; j += 1) {
      assert.ok(Math.hypot(circles[i].x - circles[j].x, circles[i].y - circles[j].y) >= circles[i].r + circles[j].r);
    }
  }
  const base = { nodes: [{ id: "a" }], edges: [{ id: "e1" }] };
  const first = mergeAdditions(base, { nodes: [], edges: [], positions: new Map() },
    { nodes: [{ id: "a" }, { id: "b" }], edges: [{ id: "e1" }, { id: "e2" }] }, new Map([["b", { x: 1, y: 2, r: 7 }]]));
  assert.deepEqual(first.nodes.map((n) => n.id), ["b"]);
  assert.deepEqual(first.edges.map((e) => e.id), ["e2"]);
  const second = mergeAdditions(base, first, { nodes: [{ id: "b" }, { id: "c" }], edges: [{ id: "e3" }] },
    new Map([["b", { x: 99, y: 99, r: 7 }], ["c", { x: 5, y: 5, r: 7 }]]));
  assert.deepEqual(second.positions.get("b"), { x: 1, y: 2, r: 7 }, "an entity already added keeps its place");
  assert.deepEqual(second.nodes.map((n) => n.id), ["b", "c"]);
});

test("additive Expand asks with expand_node_id and the shown ids, never with focus_node_id (that is a 422)", () => {
  const url = new URL(graphExpandUrl("ws", "n1", "n1,n2", 30, ["manual"]), "https://x.test");
  assert.equal(url.searchParams.get("expand_node_id"), "n1");
  assert.equal(url.searchParams.get("current_node_ids"), "n1,n2");
  assert.equal(url.searchParams.get("max_nodes"), "30");
  assert.equal(url.searchParams.has("focus_node_id"), false);
});

test("types an Expand brings in take free colours; no colour already shown changes", () => {
  const slots = assignTypeSlots({ Rule: 5, Team: 2 });
  const grown = withTypes(slots, ["Merchant", "Rule"]);
  assert.equal(grown.get("Rule"), slots.get("Rule"));
  assert.equal(grown.get("Team"), slots.get("Team"));
  assert.ok(grown.get("Merchant") > 0 && ![slots.get("Rule"), slots.get("Team")].includes(grown.get("Merchant")));
});
