import assert from "node:assert/strict";
import { test } from "node:test";
import { START_CONTEXT, contextLabel, focusHeading, popContext, pushContext } from "../../src/admin/components/entityGraph/entityGraphFocusTrail.ts";

test("nested neighbourhoods return to each previous context in order", () => {
  const search = { ...START_CONTEXT, query: "Jackson", selectedId: "j2" };
  const outer = { query: "", focusNodeId: "j2", focusName: "Jackson 2", selectedId: "sb4" };
  let trail = pushContext(pushContext([], search), outer);
  let step = popContext(trail);
  assert.deepEqual(step.previous, outer);
  step = popContext(step.trail);
  assert.deepEqual(step.previous, search);
  assert.equal(popContext(step.trail), null);
});

test("labels name the active neighbourhood and where Back goes", () => {
  assert.equal(focusHeading({ ...START_CONTEXT, focusNodeId: "j2", focusName: "Jackson 2" }), "Relationships around Jackson 2");
  assert.equal(focusHeading({ ...START_CONTEXT, query: "Jackson" }), null);
  assert.equal(contextLabel({ ...START_CONTEXT, query: "Jackson" }), "results for “Jackson”");
  assert.equal(contextLabel({ ...START_CONTEXT, focusNodeId: "x", focusName: "Spring Boot 4.0" }), "relationships around Spring Boot 4.0");
  assert.equal(contextLabel(START_CONTEXT), "the full view");
});
