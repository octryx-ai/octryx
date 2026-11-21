import assert from "node:assert/strict";
import { test } from "node:test";
import { CHAT_STARTERS, knowledgeDocumentsHref, shortRuntimeLabel, workspaceHint } from "../../src/chat/chatOnboarding.ts";

test("first use is customer-facing English, not an internal runtime test", () => {
  assert.ok(CHAT_STARTERS.length >= 3);
  for (const starter of CHAT_STARTERS) assert.doesNotMatch(starter.prompt + starter.label, /Runtime-Fallback|testen|Kubernetes/);
  assert.match(workspaceHint("Global"), /No workspace is selected/);
  assert.match(workspaceHint("Petclinic"), /Petclinic/);
  // Copy is conditional: it never claims that sources exist or were retrieved.
  assert.match(workspaceHint("Petclinic"), /where they exist/);
});

test("the model identifier moves into run details", () => {
  assert.equal(shortRuntimeLabel("Auto · AWS Bedrock / anthropic.claude-sonnet-4-5-20250929-v1:0"), "Auto · AWS Bedrock");
  assert.equal(shortRuntimeLabel("Automatic"), "Automatic");
});

test("the documents link keeps the chat's workspace (judge B2 review)", () => {
  const href = new URL(knowledgeDocumentsHref("petclinic-id"), "http://x");
  assert.equal(href.searchParams.get("workspace_id"), "petclinic-id");
  assert.equal(href.searchParams.get("tab"), "knowledgeSources");
  assert.equal(new URL(knowledgeDocumentsHref(""), "http://x").searchParams.has("workspace_id"), false);
});
