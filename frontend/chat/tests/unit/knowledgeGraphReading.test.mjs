import assert from "node:assert/strict";
import { test } from "node:test";
import {
  detailClaims, fitViewBox, isSelfEdge, labelFontSize, labelledIds, linkCounts, linkLabel, rankEntities,
  selfLoopPath,
} from "../../src/admin/components/entityGraph/entityGraphReading.ts";
import { typeLegend } from "../../src/admin/components/entityGraph/entityGraphPresentation.ts";

const node = (id, name = id) => ({ id, display_name: name });
const edge = (source, target) => ({ source, target });

test("the entity list ranks search matches first, then by visible relationships, then by name", () => {
  const nodes = [node("a", "Alpha"), node("b", "Beta"), node("c", "Gamma"), node("d", "Delta")];
  const edges = [edge("a", "b"), edge("a", "c"), edge("b", "c"), edge("a", "d")];
  assert.deepEqual(rankEntities(nodes, edges, new Set()).map((entity) => entity.id), ["a", "b", "c", "d"]);
  assert.deepEqual(rankEntities(nodes, edges, new Set(["d"])).map((entity) => entity.id), ["d", "a", "b", "c"]);
  assert.equal(rankEntities([node("x", "")], [], new Set())[0].name, "Unnamed entity");
});

test("a relationship with the same entity on both ends is one self link, not two neighbours", () => {
  assert.equal(isSelfEdge(edge("p", "p")), true);
  const counts = linkCounts([edge("p", "p"), edge("p", "q")]);
  assert.deepEqual(counts.get("p"), { links: 2, selfLinks: 1 });
  assert.deepEqual(counts.get("q"), { links: 1, selfLinks: 0 });
  assert.equal(linkLabel(counts.get("p")), "2 relationships, 1 to itself");
  assert.match(selfLoopPath({ x: 100, y: 100, radius: 10 }), /^M 94\.0 92\.0 C /);
});

test("the drawing starts fitted to its content and labels render at least 12 px on screen", () => {
  const points = [{ id: "a", x: 500, y: 300, radius: 10 }, { id: "b", x: 800, y: 500, radius: 20 }];
  const box = fitViewBox(points, { x: 0, y: 0, w: 1200, h: 760 });
  assert.ok(box.x < 480 && box.x + box.w > 820, "covers every node with side padding");
  assert.ok(box.w < 1200, "a compact cluster is zoomed in instead of drawn in the full canvas");
  const font = labelFontSize(box, 470, 420);
  const screenPx = font / Math.max(box.w / 470, box.h / 420);
  assert.ok(screenPx >= 12, `label is ${screenPx}px on screen`);
  assert.deepEqual(fitViewBox([], { x: 0, y: 0, w: 1, h: 1 }), { x: 0, y: 0, w: 1, h: 1 });
});

test("labels go to the selection, its neighbours and matches first, then to the highest ranked", () => {
  const ranked = ["a", "b", "c", "d", "e", "f", "g", "h"].map((id) => ({ id }));
  const ids = labelledIds(ranked, 3, "h", new Set(["g"]), new Set(["f"]));
  assert.deepEqual([...ids], ["h", "g", "f"]);
  assert.deepEqual([...labelledIds(ranked, 3, "", new Set(), new Set())], ["a", "b", "c"]);
  assert.equal([...labelledIds(ranked, ranked.length, "h", new Set(["g"]), new Set(["f"]))].length, 8);
});

test("an unclassified graph states it instead of offering a one-chip type filter", () => {
  assert.deepEqual(typeLegend({ entity: 25 }), { kind: "note", text: "Entity types are not classified for this workspace." });
  assert.equal(typeLegend({ person: 3, product: 2 }).kind, "filter");
  assert.equal(typeLegend({}), null);
});

test("details do not repeat a relationship's statement as a separate fact", () => {
  const claims = [{ statement: "A renamed to B", evidence_key: "k1" }, { statement: "A requires C", evidence_key: "k2" }];
  const relations = [{ description: "A renamed to B", evidence_key: "k1" }];
  assert.deepEqual(detailClaims({ claims, relations }).map((claim) => claim.evidence_key), ["k2"]);
});
