// Graph search states why each entity matched, by the server's own rule (C3 rework).
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  matchBases, matchBasisLabel, normalizeQuery, viewSummary,
} from "../../src/admin/components/entityGraph/entityGraphMatches.ts";

const node = (id, display_name) => ({ id, display_name });
const edge = (source, target, description) => ({ id: `${source}-${target}`, source, target, description });
const payload = {
  nodes: [node("j2", "Jackson 2"), node("cbor", "CBOR"), node("sb", "Spring Boot"), node("x", "Mystery")],
  edges: [edge("cbor", "sb", "Spring Boot reads CBOR through JACKSON data formats"), edge("j2", "sb", "auto-configured")],
  match_ids: ["j2", "cbor", "sb", "x"],
};

test("a name match is a name match; an end of a matching statement is a statement match", () => {
  const bases = matchBases(payload, "  Jackson ");
  assert.equal(bases.get("j2"), "name");
  assert.equal(bases.get("cbor"), "statement");
  assert.equal(bases.get("sb"), "statement");
  assert.equal(bases.get("x"), "server", "an unexplained server match is never given a guessed basis");
  assert.equal(matchBases(payload, "").size, 0);
  assert.equal(matchBases(null, "jackson").size, 0);
  assert.equal(normalizeQuery(`  ${"a".repeat(600)} `).length, 500);
});

test("only ids the server matched are classified", () => {
  const bases = matchBases({ ...payload, match_ids: ["j2"] }, "jackson");
  assert.deepEqual([...bases.keys()], ["j2"]);
});

test("labels state the basis truthfully", () => {
  assert.equal(matchBasisLabel("name", " Jackson "), "Name contains “Jackson”");
  assert.equal(matchBasisLabel("statement", "Jackson"), "A relationship statement mentions “Jackson”");
  assert.equal(matchBasisLabel("server", "Jackson"), "Matched by the server");
});

test("the summary counts this view only and splits matches by basis", () => {
  const base = { entities: 25, relationships: 14, truncated: false, query: "", bases: new Map() };
  assert.equal(viewSummary(base), "Showing 25 entities and 14 relationships in this view.");
  assert.equal(viewSummary({ ...base, truncated: true }), "Showing 25 entities and 14 relationships in this view (bounded).");
  const bases = new Map([["a", "name"], ["b", "name"], ["c", "statement"]]);
  const text = viewSummary({ ...base, relationships: 23, query: "Jackson", bases });
  assert.equal(text, "Showing 25 entities and 23 relationships in this view. 3 entities match “Jackson”: "
    + "2 by name, 1 via a relationship statement; 22 connected entities shown for context.");
  assert.doesNotMatch(text, /name matches/);
  const all = viewSummary({ ...base, entities: 1, relationships: 1, query: "q", bases: new Map([["a", "server"]]), capped: true });
  assert.equal(all, "Showing 1 entity and 1 relationship in this view. 1+ entity matches “q”: 0 by name, "
    + "0 via a relationship statement, 1 matched by the server.");
  assert.match(viewSummary({ ...base, query: "none" }), /No entities match “none” in this view\.$/);
});
