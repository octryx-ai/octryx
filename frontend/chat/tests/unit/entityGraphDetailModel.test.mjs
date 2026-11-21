// Detail pane reading model: humanised relations, one trust label, stored-vs-shown scope (C3 rework).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  detailScopeLine, humanizeRelation, incidentEdgeCount, relationRows, trustLabels,
} from "../../src/admin/components/entityGraph/entityGraphDetailModel.ts";

test("relation codes read as words", () => {
  assert.equal(humanizeRelation("HAS_PROPERTIES_UNDER"), "has properties under");
  assert.equal(humanizeRelation("dependsOn"), "depends on");
  assert.equal(humanizeRelation(""), "unnamed relationship");
});

test("trust and status never render the same word twice", () => {
  assert.deepEqual(trustLabels("extracted", "extracted"), { trust: "Extracted · not reviewed", status: null });
  assert.deepEqual(trustLabels("extracted", "active"), { trust: "Extracted · not reviewed", status: null });
  assert.deepEqual(trustLabels("reviewed", "superseded"), { trust: "Reviewed", status: "Superseded" });
  assert.equal(trustLabels("", "").trust, "Trust not stated");
});

const relation = (peer_id, direction, edge_type, description, extra = {}) =>
  ({ peer_id, peer_name: peer_id.toUpperCase(), peer_type: "entity", direction, edge_type, description, ...extra });
const detail = {
  id: "j", truncated: true,
  relations: [
    relation("far", "in", "SUPPORTS", "Far supports J"),
    relation("sb", "out", "HAS_PROPERTIES_UNDER", "J properties under spring.jackson", { evidence_key: "k1" }),
    relation("j", "out", "SAME_AS", "J is J"),
    relation("sb", "in", "HAS_PROPERTIES_UNDER", "J properties under spring.jackson"),
  ],
};
const viewEdges = [
  { id: "e1", source: "j", target: "sb", edge_type: "HAS_PROPERTIES_UNDER", description: "J properties under spring.jackson", evidence_key: "k1" },
  { id: "e2", source: "j", target: "j", edge_type: "SAME_AS", description: "J is J" },
  { id: "e3", source: "sb", target: "other", edge_type: "USES", description: "unrelated" },
];

test("the scope line separates stored relationships from those shown in this view", () => {
  assert.equal(incidentEdgeCount("j", viewEdges), 2);
  assert.equal(detailScopeLine(detail, 2), "4 available relationships in this neighbourhood (bounded, more may exist) · 2 shown in the current view");
  assert.equal(detailScopeLine({ relations: [relation("a", "out", "X", "")], truncated: false }, 0),
    "1 available relationship in this neighbourhood · 0 shown in the current view");
});

test("rows mark exactly the stored relationships that this view shows; self references stay", () => {
  const rows = relationRows(detail, viewEdges, new Set(["j", "sb", "other"]));
  assert.deepEqual(rows.map((row) => [row.kind, row.peerId, row.inView]), [
    ["out", "sb", true], ["self", "j", true], ["in", "far", false], ["in", "sb", false],
  ]);
  assert.equal(rows[0].relation, "has properties under");
  assert.equal(rows[0].code, "HAS_PROPERTIES_UNDER");
  assert.equal(rows[0].peerInView, true);
  assert.equal(rows[2].peerInView, false);
  assert.equal(rows.filter((row) => row.inView).length, incidentEdgeCount("j", viewEdges));
});
