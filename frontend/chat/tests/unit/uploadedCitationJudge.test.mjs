import assert from "node:assert/strict";
import { test } from "node:test";
import { originalContentUrl } from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeRequest.ts";
import { collectAnswerSources, safeSourceUrl } from "../../src/chat/evidence/answerSourceLinks.ts";

test("the actual uploaded original route already appears in Sources when an answer links it", () => {
  const origin = "http://localhost:8090";
  const target = originalContentUrl(
    "785b4554-bfbc-41f6-9f39-d408868134b2",
    "11111111111141118111111111111111",
    "22222222222242228222222222222222",
  );
  assert.equal(safeSourceUrl(target, origin), origin + target);
  const link = {
    getAttribute: () => target,
    textContent: "Uploaded runbook (revision 1)",
    closest: () => ({ textContent: "The drill runs on Tuesday." }),
  };
  const result = collectAnswerSources({ querySelectorAll: () => [link] }, origin);
  assert.equal(result.excluded, 0);
  assert.deepEqual(result.sources, [{
    url: origin + target,
    label: "Uploaded runbook (revision 1)",
    statement: "The drill runs on Tuesday.",
  }]);
});
