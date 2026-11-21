// Knowledge graph without entity types (Preview's Acme Orders): groups from the graph's structure
// (Louvain, deterministic), named after their hub; loosely connected entities on an outer ring; the legend note.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  groupOfAdded, groupsNote, louvain, LOOSE_GROUP, needsStructureGroups, structureGroups,
} from "../../src/admin/components/entityGraph/kgCommunities.ts";
import { layoutGraph } from "../../src/admin/components/entityGraph/kgLayout.ts";

// Three dense cliques joined by one bridge each, plus isolated entities and one pair.
function sample() {
  const nodes = [];
  const edges = [];
  const add = (id, name = id) => { nodes.push({ id, display_name: name, node_type: "entity" }); };
  const link = (a, b) => edges.push({ id: `${a}-${b}`, source: a, target: b });
  for (const [prefix, hub] of [["j", "JMS"], ["k", "Kafka plug-in"], ["t", "TLSv1.3"]]) {
    add(`${prefix}0`, hub);
    for (let i = 1; i < 6; i += 1) { add(`${prefix}${i}`, `${hub} part ${i}`); link(`${prefix}0`, `${prefix}${i}`); }
    link(`${prefix}1`, `${prefix}2`); link(`${prefix}3`, `${prefix}4`);
  }
  link("j1", "k1"); link("k3", "t3");
  for (let i = 0; i < 5; i += 1) add(`lone${i}`, `UTF-${i}`);
  add("p1", "JSON"); add("p2", "XSLT"); link("p1", "p2");
  return { nodes, edges };
}

test("Louvain finds the dense groups and is the same on every run and in any input order", () => {
  const { nodes, edges } = sample();
  const first = louvain(nodes, edges);
  const again = louvain([...nodes].reverse(), [...edges].reverse());
  assert.deepEqual([...again.entries()].sort(), [...first.entries()].sort());
  for (const prefix of ["j", "k", "t"]) {
    const c = first.get(`${prefix}0`);
    for (let i = 1; i < 5; i += 1) assert.equal(first.get(`${prefix}${i}`), c, `${prefix}${i} with its hub`);
  }
  assert.notEqual(first.get("j0"), first.get("k0"));
});

test("groups are named after their hub; isolated entities and pairs are 'loosely connected'; hubs keep labels", () => {
  const { nodes, edges } = sample();
  const grouping = structureGroups(nodes, edges);
  assert.deepEqual(grouping.groups.map((group) => [group.label, group.size]),
    [["around JMS", 6], ["around Kafka plug-in", 6], ["around TLSv1.3", 6], [LOOSE_GROUP, 7]]);
  assert.equal(grouping.groupOf.get("j3"), "around JMS");
  assert.equal(grouping.groupOf.get("lone2"), LOOSE_GROUP);
  assert.equal(grouping.groupOf.get("p1"), LOOSE_GROUP, "a pair is too small to be a group");
  assert.deepEqual([...grouping.hubs].sort(), ["j0", "k0", "t0"], "labels stay on the hub of each group");
  assert.equal(groupOfAdded("new", [{ source: "new", target: "k2" }, { source: "j1", target: "new" }, { source: "new", target: "k3" }],
    grouping.groupOf), "around Kafka plug-in", "an entity an Expand adds joins the group it links to most");
  assert.equal(groupOfAdded("x", [], grouping.groupOf), LOOSE_GROUP);
});

test("groups replace types only when there is no more than one type", () => {
  assert.equal(needsStructureGroups([{ node_type: "entity" }, { node_type: "entity" }]), true);
  assert.equal(needsStructureGroups([{ node_type: "Rule" }, { node_type: "Team" }]), false);
  assert.equal(needsStructureGroups([{ node_type: "entity" }]), false);
  assert.match(groupsNote("entity"), /not classified.*Colours show groups of closely linked entities/s);
  assert.match(groupsNote("Rule"), /one type \(Rule\)/);
});

test("loosely connected entities sit on a ring outside every group, never in the middle; nothing overlaps", () => {
  const { nodes, edges } = sample();
  const grouping = structureGroups(nodes, edges);
  const degree = new Map();
  for (const edge of edges) for (const id of [edge.source, edge.target]) degree.set(id, (degree.get(id) ?? 0) + 1);
  const view = nodes.map((node) => ({ id: node.id, node_type: grouping.groupOf.get(node.id), degree: degree.get(node.id) ?? 0 }));
  const layout = layoutGraph(view, edges, { ring: LOOSE_GROUP });
  const ring = layout.clusters.find((cluster) => cluster.type === LOOSE_GROUP);
  assert.ok(ring, "the ring is a cluster with a label");
  for (const cluster of layout.clusters.filter((entry) => entry.type !== LOOSE_GROUP)) {
    for (const node of view.filter((entry) => entry.node_type === LOOSE_GROUP)) {
      const at = layout.nodes.get(node.id);
      assert.ok(Math.hypot(at.x - cluster.x, at.y - cluster.y) > cluster.r + at.r, `${node.id} sits outside ${cluster.type}`);
    }
  }
  const points = [...layout.nodes.values()];
  for (let i = 0; i < points.length; i += 1) {
    for (let j = i + 1; j < points.length; j += 1) {
      assert.ok(Math.hypot(points[i].x - points[j].x, points[i].y - points[j].y) >= points[i].r + points[j].r);
    }
  }
});

test("the outer ring spreads round the whole circle, and cluster names that would collide wait for zoom", async () => {
  const { placeClusterLabels } = await import("../../src/admin/components/entityGraph/kgView.ts");
  const ring = Array.from({ length: 8 }, (_, i) => ({ id: `l${i}`, node_type: LOOSE_GROUP, degree: 0 }));
  const core = Array.from({ length: 4 }, (_, i) => ({ id: `c${i}`, node_type: "around A", degree: 3 }));
  const layout = layoutGraph(core.concat(ring), [], { ring: LOOSE_GROUP });
  const angles = ring.map((node) => { const at = layout.nodes.get(node.id); return Math.atan2(at.y, at.x); });
  const quadrants = new Set(angles.map((angle) => Math.floor(((angle + Math.PI) / (2 * Math.PI)) * 4) % 4));
  assert.equal(quadrants.size, 4, "on every side, not bunched in one arc");
  const spots = [
    { type: "around JMS", x: 0, y: 0, r: 40, size: 20, text: "around JMS 20" },
    { type: "around Kafka", x: 30, y: 0, r: 40, size: 10, text: "around Kafka 10" },
  ];
  assert.deepEqual([...placeClusterLabels(spots, 1).keys()], ["around JMS"], "the larger group keeps its name");
  assert.equal(placeClusterLabels(spots, 8).size, 2, "zoomed in, both fit");
});

test("the ring frames the groups closely; ring lines are faint until hovered or selected; group names beat entity labels", async () => {
  const { edgeLook } = await import("../../src/admin/components/entityGraph/kgView.ts");
  const { placeLabels } = await import("../../src/admin/components/entityGraph/entityGraphLabels.ts");
  const core = Array.from({ length: 12 }, (_, i) => ({ id: `c${i}`, node_type: i < 6 ? "around A" : "around B", degree: 2 }));
  const ring = Array.from({ length: 10 }, (_, i) => ({ id: `l${i}`, node_type: LOOSE_GROUP, degree: 1 }));
  const layout = layoutGraph(core.concat(ring), [], { ring: LOOSE_GROUP, airy: true });
  const loose = layout.clusters.find((cluster) => cluster.type === LOOSE_GROUP);
  const outer = Math.max(...layout.clusters.filter((c) => c.type !== LOOSE_GROUP)
    .map((c) => Math.hypot(c.x - loose.x, c.y - loose.y) + c.r));
  assert.ok(loose.r - outer < 120, `ring ${Math.round(loose.r)} hugs the outermost group at ${Math.round(outer)}`);
  const faint = new Set(["l1"]);
  assert.equal(edgeLook({ id: "e", source: "l1", target: "c1" }, "", "", faint), "faint");
  assert.equal(edgeLook({ id: "e", source: "l1", target: "c1" }, "", "e", faint), "hover");
  assert.equal(edgeLook({ id: "e", source: "l1", target: "c1" }, "c1", "", faint), "focus");
  assert.equal(edgeLook({ id: "e", source: "c2", target: "c1" }, "", "", faint), "idle");
  const node = { id: "n", x: 0, y: 0, radius: 6, display_name: "blacklist-service" };
  assert.equal(placeLabels([node], ["n"], 12).size, 1);
  const name = { left: -60, top: 6, right: 60, bottom: 30 };
  assert.equal(placeLabels([node], ["n"], 12, undefined, [name]).size, 0, "the entity label gives way to the group name");
});
