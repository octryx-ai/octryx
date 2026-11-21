// One canonical place to manage an agent.
import assert from "node:assert/strict";
import { test } from "node:test";
import { listAdminAreaTabRefs, resolveAdminAreaTab } from "../../src/admin/config/adminPanelAreas.ts";
import { agentPageHref, readAgentIdFromSearch, withAgentId } from "../../src/admin/agentLinks.ts";
import {
  agentTestChatHref,
  executionSourceLabel,
  agentWorkspaceOptions,
  revisionLabel,
  stepToolsLabel,
} from "../../src/admin/components/agentsTab/agentWorkspaceModel.ts";

test("Agents is the one agent place; an unknown page id opens the area's default", () => {
  assert.equal(listAdminAreaTabRefs("workflows").find((ref) => ref.id === "modes"), undefined);
  assert.equal(resolveAdminAreaTab("workflows", "modes"), "agents");
  const agentPlaces = listAdminAreaTabRefs("workflows").filter((ref) => !ref.hidden && /agent/i.test(ref.label ?? ""));
  assert.deepEqual(agentPlaces.map((ref) => ref.id), ["agents"]);
});

test("workflows link to the canonical agent page", () => {
  const href = agentPageHref("a-1");
  assert.equal(readAgentIdFromSearch(new URL(href, "http://x").search), "a-1");
  assert.match(href, /tab=agents/);
  assert.equal(new URL(withAgentId("http://x/chat?tab=agents&agent_id=a", null)).searchParams.has("agent_id"), false);
});

test("agent workspace choices are active only; the assigned inactive one stays visible and labelled (J-E-004)", () => {
  const projects = [
    { id: "a", name: "Petclinic", is_active: true },
    { id: "b", name: "Old fixture", is_active: false },
    { id: "c", name: "Other fixture", is_active: false },
  ];
  assert.deepEqual(agentWorkspaceOptions(projects).map((o) => o.id), ["a"]);
  assert.deepEqual(agentWorkspaceOptions(projects, "b").map((o) => o.label), ["Petclinic", "Old fixture (inactive)"]);
});

test("test in chat names the agent and its workspace explicitly (J-E-005)", () => {
  const url = new URL(agentTestChatHref("ag 1", "ws-1"), "http://x");
  assert.equal(url.searchParams.get("new"), "true");
  assert.equal(url.searchParams.get("agent_id"), "ag 1");
  assert.equal(url.searchParams.get("project_id"), "ws-1");
  assert.equal(url.searchParams.get("workspace_id"), "ws-1");
});

test("revision and tool texts state facts, never 'all registered tools'", () => {
  assert.equal(revisionLabel({ id: "r", revision_number: 3, status: "draft" }), "Draft revision 3 · not published");
  assert.equal(revisionLabel(null), "No revision recorded yet");
  assert.doesNotMatch(stepToolsLabel([]), /all registered/i);
  assert.match(stepToolsLabel([]), /mode, workspace connectors and policy/);
  assert.equal(stepToolsLabel(["read_file"]), "Limited to: read_file");
});

test("the page says which revision a test runs and blocks a run the platform would refuse", () => {
  const draftRev = { id: "r2", revision_number: 2, status: "draft" };
  assert.match(executionSourceLabel({ mode: "draft", published_revision_number: null }, draftRev).text, /including unpublished changes/);
  const published = executionSourceLabel({ mode: "published", published_revision_number: 1 }, draftRev);
  assert.equal(published.blocked, false);
  assert.match(published.text, /published revision 1\. Newer draft changes are not used until published/);
  assert.equal(executionSourceLabel({ mode: "published", published_revision_number: null }, draftRev).blocked, true);
  assert.equal(executionSourceLabel({ mode: "unknown", published_revision_number: null }, null).blocked, true);
  assert.deepEqual(executionSourceLabel(null, null), { text: "", blocked: false });
});
