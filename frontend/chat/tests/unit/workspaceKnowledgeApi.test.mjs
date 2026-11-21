import assert from "node:assert/strict";
import { test } from "node:test";
import { knowledgeBase, request, splitProducts } from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeRequest.ts";

test("the Knowledge API path is scoped by the encoded workspace id", () => {
  assert.equal(knowledgeBase("a/b"), "/api/v1/workspaces/a%2Fb/knowledge");
});

test("products are lower-case keys without blanks", () => {
  assert.deepEqual(splitProducts(" Spring-Boot, ,data-platform "), ["spring-boot", "data-platform"]);
});

test("a refused Knowledge request keeps its status and the state the server named", async () => {
  const saved = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ detail: "Workspace knowledge storage is not configured." }),
    { status: 503, headers: { "Content-Type": "application/json", "X-Knowledge-State": "needs_configuration" } });
  try {
    await assert.rejects(() => request("/api/v1/workspaces/w/knowledge/search", { method: "POST", body: "{}" }),
      (error) => error.message === "Workspace knowledge storage is not configured." && error.status === 503
        && error.state === "needs_configuration");
  } finally { globalThis.fetch = saved; }
});
