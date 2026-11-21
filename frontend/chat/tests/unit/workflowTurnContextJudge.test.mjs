import test from "node:test";
import assert from "node:assert/strict";
import { repeatedTurnMessageIds } from "../../src/chat/run/workflowTurnContext.ts";

// The persisted workspace serializer maps each assistant message to its own trace.
// One user turn in the live repository replay contains five different trace IDs.
const row = (id, role, turnTraceId) => ({kind: "message", message: {id, role, turnTraceId}});
test("one user turn's progress messages have distinct trace IDs, not a shared turn ID", () => {
  const items = [row("u1", "user"), row("a1", "assistant", "trace1"),
    row("a2", "assistant", "trace2"), row("a3", "assistant", "trace3")];
  assert.deepEqual([...repeatedTurnMessageIds(items)], ["a2", "a3"]);
});
test("a new user request keeps its own context even when its workflow is unchanged", () => {
  const items = [row("u1", "user"), row("a1", "assistant", "trace1"),
    row("a2", "assistant", "trace2"), row("u2", "user"), row("a3", "assistant", "trace3")];
  assert.deepEqual([...repeatedTurnMessageIds(items)], ["a2"]);
});
