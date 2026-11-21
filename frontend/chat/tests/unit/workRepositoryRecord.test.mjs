// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workRepositoryRecord.test.mjs
//
// Settings → Workspace → Repositories: one record per repository with its
// source, branch, owners and Coding setup; adding one picks a Knowledge git source (no URL is typed); the record's
// coding setup is edited there; Work → Repositories redirects to it. Requests are stubs; names invented.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { setupText, sourceText } from "../../src/admin/components/projectsTab/repositories/workspaceRepositoriesApi.ts";
import { workLocation } from "../../src/chat/work/workNavRedirects.ts";
import { button, byTestId, load, server, text } from "./workCodingSupport.mjs";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const REPOS = [
  { id: "r1", name: "claims-api", provider: "knowledge_snapshot", default_branch: "main", source: { kind: "knowledge_source", name: "claims-api" },
    owners: ["Claims backend team"], coding_setup: { configured: ["build", "test", "lint"], missing: [] }, last_index_status: "ready" },
  { id: "r2", name: "claims-web", provider: "knowledge_snapshot", default_branch: "main", source: { kind: "knowledge_source", name: "claims-web" },
    owners: [], coding_setup: { configured: ["build"], missing: ["test", "lint"] }, last_index_status: "ready" },
];

test("setup and source in words; Work has no Repositories page address (it lives in the Workspace settings)", () => {
  assert.deepEqual(setupText(REPOS[0].coding_setup), { text: "build · test · lint", missing: false });
  assert.deepEqual(setupText(REPOS[1].coding_setup), { text: "test, lint missing", missing: true });
  assert.equal(sourceText(REPOS[0].source), 'Knowledge source "claims-api"');
  assert.deepEqual(workLocation("?work_view=repositories"), workLocation(""));
});

test("rendered: the records table, add from a Knowledge git source, and the coding setup saved on the record", async () => {
  const srv = server((url, method) => {
    if (url.endsWith("/repositories/sources")) return { status: 200, body: { items: [{ id: "k1", name: "claims-api" }, { id: "k2", name: "claims-batch" }] } };
    if (url.endsWith("/from-source")) return { status: 200, body: { repository_id: "r3" } };
    if (url.endsWith("/coding-setup") && method === "GET") return { status: 200, body: { coding_setup: { owners: ["Claims backend team"], test_commands: ["./gradlew test"] } } };
    if (url.endsWith("/coding-setup")) return { status: 200, body: {} };
    return { status: 200, body: { items: REPOS } };
  });
  const { WorkspaceRepositoriesSection } = load("admin/components/projectsTab/repositories/WorkspaceRepositoriesSection.tsx", { fetch: srv.fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkspaceRepositoriesSection, { workspaceId: "ws-1" })); });
  const rows = byTestId(view, "repository-row");
  assert.match(text(rows[0]), /claims-apiKnowledge source "claims-api"mainClaims backend teambuild · test · lint/);
  assert.match(text(rows[1]), /test, lint missing/);
  await act(async () => { button(view, "+ Set up from a Knowledge source").props.onClick(); });
  assert.match(text(byTestId(view, "repository-sources")[0]), /claims-batch/);
  assert.doesNotMatch(text(byTestId(view, "repository-sources")[0]), /claims-api/, "a source with a record is not offered twice");
  await act(async () => { button(view, "Add").props.onClick(); });
  assert.deepEqual(srv.calls.find((call) => call.url.endsWith("/from-source")).body, { connector_id: "k2" });
  await act(async () => { rows[0].props.onClick(); });
  const record = byTestId(view, "repository-record")[0];
  assert.match(text(record), /Repository · claims-api/);
  const testCommands = record.findAll((node) => node.props["aria-label"] === "Test commands")[0];
  assert.equal(testCommands.props.value, "./gradlew test");
  await act(async () => { testCommands.props.onChange({ target: { value: "./gradlew test\n./gradlew check" } }); });
  await act(async () => { button(view, "Save coding setup").props.onClick(); });
  const saved = srv.calls.find((call) => call.method === "PUT");
  assert.ok(saved.url.endsWith("/repositories/r1/coding-setup"));
  assert.deepEqual(saved.body.test_commands, ["./gradlew test", "./gradlew check"]);
  act(() => view.unmount());
});
