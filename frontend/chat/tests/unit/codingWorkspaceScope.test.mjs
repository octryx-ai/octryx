// Coding shows the selected Workspace only. The coding-session list names the Workspace, so an empty
// Workspace lists no session of another one; without a Workspace the caller's whole scope is listed.
import assert from "node:assert/strict";
import { test } from "node:test";

const calls = [];
globalThis.fetch = async (url) => {
  calls.push(String(url));
  const body = String(url).includes("coding-sessions") ? { items: [] } : [];
  return { ok: true, status: 200, json: async () => body, text: async () => JSON.stringify(body), headers: new Map() };
};

const { loadCodingWorkspaceData } = await import("../../src/chat/coding/codingApi.ts");

test("the coding-session list names the selected Workspace", async () => {
  calls.length = 0;
  await loadCodingWorkspaceData("ws-first-run");
  const sessions = calls.find((url) => url.includes("/coding-sessions"));
  assert.ok(sessions, calls.join(" | "));
  const params = new URL(sessions, "http://local").searchParams;
  assert.equal(params.get("project_id"), "ws-first-run");
  assert.equal(params.get("limit"), "1000");
});

test("without a Workspace the list is not narrowed", async () => {
  calls.length = 0;
  await loadCodingWorkspaceData("");
  const sessions = calls.find((url) => url.includes("/coding-sessions"));
  assert.equal(new URL(sessions, "http://local").searchParams.get("project_id"), null);
});
