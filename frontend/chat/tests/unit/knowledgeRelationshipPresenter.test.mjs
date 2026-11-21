import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BINARY_RELATIONS,
  MAX_RELATIONSHIPS,
  RELATIONSHIP_PAGE,
  nextRelationshipLimit,
  presentFact,
  relationLabel,
  relationshipCountText,
} from "../../src/chat/knowledge/relationshipPresenter.ts";

const fact = (relation, subject, object, statement = "") => ({ relation, subject, object, fact: statement });

test("the statement is the headline", () => {
  const view = presentFact(fact("REMOVED", "Undertow", "Spring Boot 4.0", "Undertow support is dropped in Spring Boot 4."));
  assert.equal(view.headline, "Undertow support is dropped in Spring Boot 4.");
});

test("binary relations keep their object", () => {
  for (const relation of ["RENAMED", "REPLACED_BY", "MOVED_TO", "REQUIRES"]) {
    assert.ok(BINARY_RELATIONS.has(relation));
    const view = presentFact(fact(relation, "@JsonComponent", "@JacksonComponent", "x"));
    assert.equal(view.object, "@JacksonComponent", relation);
  }
  assert.equal(presentFact(fact("RENAMED", "a", "b")).relation, "renamed to");
});

test("unary relations never show the arbitrary target entity", () => {
  for (const relation of ["REMOVED", "DEPRECATED", "INTRODUCED", "DEFAULT_CHANGED", "DESCRIBES", "USES"]) {
    const view = presentFact(fact(relation, "Liveness probes", "Spring Boot 4.0 Migration Guide", "statement"));
    assert.equal(view.object, null, relation);
    assert.equal(view.subject, "Liveness probes");
  }
  assert.equal(presentFact(fact("DESCRIBES", "a", "b")).typed, false);
  assert.equal(presentFact(fact("DEFAULT_CHANGED", "a", "b")).relation, "default changed");
  assert.equal(relationLabel("PART_OF"), "part of");
});

test("a binary relation without a distinct object degrades to subject and relation", () => {
  assert.equal(presentFact(fact("RENAMED", "X", "")).object, null);
  assert.equal(presentFact(fact("RENAMED", "X", "X")).object, null);
  assert.equal(presentFact(fact("RENAMED", "X", "Y")).headline, "X renamed to Y");
});

test("show more grows by a page up to the server maximum, and stops on a short page", () => {
  assert.equal(nextRelationshipLimit(RELATIONSHIP_PAGE, RELATIONSHIP_PAGE), 2 * RELATIONSHIP_PAGE);
  assert.equal(nextRelationshipLimit(RELATIONSHIP_PAGE, 12), null);
  assert.equal(nextRelationshipLimit(180, 180), MAX_RELATIONSHIPS);
  assert.equal(nextRelationshipLimit(MAX_RELATIONSHIPS, MAX_RELATIONSHIPS), null);
  assert.equal(MAX_RELATIONSHIPS, 200);
});

test("counts are truthful about the range and about a query page", () => {
  const facts = new Array(30).fill(fact("REMOVED", "a", "b"));
  assert.equal(
    relationshipCountText({ facts, kind_counts: { REMOVED: 50, RENAMED: 20 } }, false, "4.0"),
    "Showing 30 of 70 relationships up to version 4.0.",
  );
  assert.equal(relationshipCountText({ facts: facts.slice(0, 3), kind_counts: { REMOVED: 3 } }, false, "4.0"),
    "Showing all 3 relationships up to version 4.0.");
  assert.equal(relationshipCountText({ facts: facts.slice(0, 5), kind_counts: { REMOVED: 5 } }, true, "4.0"),
    "Showing the 5 best matches up to version 4.0.");
});
