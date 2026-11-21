// Collision-aware drawing labels: priority order, no overlaps, exact names elsewhere (C3 rework).
import assert from "node:assert/strict";
import { test } from "node:test";
import { labelBox, placeLabels } from "../../src/admin/components/entityGraph/entityGraphLabels.ts";

const node = (id, x, y, display_name = id, radius = 10) => ({ id, x, y, radius, display_name });
const overlap = (a, b) => a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;

test("labels never overlap each other or another node", () => {
  const nodes = Array.from({ length: 25 }, (_, i) => node(`n${i}`, (i % 5) * 60, Math.floor(i / 5) * 40,
    `Entity with a fairly long name ${i}`));
  const order = nodes.map((entry) => entry.id);
  const placed = placeLabels(nodes, order, 12);
  assert.ok(placed.size > 0 && placed.size < nodes.length, `placed ${placed.size}`);
  const boxes = [...placed].map(([id, label]) => labelBox(nodes.find((entry) => entry.id === id), label.text, 12));
  for (let i = 0; i < boxes.length; i += 1) {
    for (let j = i + 1; j < boxes.length; j += 1) assert.equal(overlap(boxes[i], boxes[j]), false);
  }
  for (const [id, label] of placed) {
    const box = labelBox(nodes.find((entry) => entry.id === id), label.text, 12);
    for (const other of nodes) {
      if (other.id === id) continue;
      const circle = { left: other.x - other.radius, right: other.x + other.radius, top: other.y - other.radius, bottom: other.y + other.radius };
      assert.equal(overlap(box, circle), false, `${id} label covers ${other.id}`);
    }
  }
});

test("priority decides who gets a contested spot; a long name is shortened before it is skipped", () => {
  const nodes = [node("a", 0, 0, "Alpha"), node("b", 30, 0, "Beta")];
  assert.deepEqual([...placeLabels(nodes, ["b", "a"], 12).keys()], ["b"]);
  assert.deepEqual([...placeLabels(nodes, ["a", "b"], 12).keys()], ["a"]);
  const crowded = [node("long", 0, 0, "Spring Boot Actuator Endpoint Configuration"), node("right", 80, 26, "R", 4)];
  const label = placeLabels(crowded, ["long"], 12).get("long");
  assert.ok(label.text.endsWith("…") && label.text.length <= 14, label.text);
  assert.ok(placeLabels([node("solo", 0, 0, "Short")], ["solo"], 12).get("solo").y > 10, "label sits below the node");
});

test("off-screen and unknown nodes do not take label space", () => {
  const nodes = [node("out", 5000, 0, "Out"), node("in", 0, 0, "In")];
  const placed = placeLabels(nodes, ["missing", "out", "in"], 12, { x: -100, y: -100, w: 200, h: 200 });
  assert.deepEqual([...placed.keys()], ["in"]);
});
