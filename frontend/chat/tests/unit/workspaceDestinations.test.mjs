import assert from "node:assert/strict";
import { test } from "node:test";
import { getWorkspaceDestinations, codingWorkspaceView } from "../../src/chat/workspaceDestinations.ts";

test("without a Workspace or the Work role: knowledge and repository exploration, no operational destinations", () => {
  const areas = getWorkspaceDestinations(false, false).map((item) => item.area);
  assert.ok(areas.includes("knowledge"));
  assert.equal(areas.includes("admin"), false);
  assert.equal(areas.includes("work"), false);
  assert.equal(areas.includes("coding"), true, "their Work entry opens the repositories");
  assert.deepEqual(getWorkspaceDestinations(false, false).filter((item) => item.area === "coding").map((item) => item.label), ["Work"]);
});

test("an operator's work destinations do not grant administrator navigation", () => {
  const areas = getWorkspaceDestinations(false, true).map((item) => item.area);
  // Work and Coding are one rail entry, "Work"; its menu holds the Coding pages.
  assert.ok(areas.includes("work") && !areas.includes("coding"));
  assert.equal(areas.includes("admin"), false);
});

test("administrator entries retain their existing tabs and each area has one destination", () => {
  const entries = getWorkspaceDestinations(true, true);
  assert.equal(new Set(entries.map((item) => item.area)).size, entries.length);
  // Settings, Runtime and Automation are Admin; Observability is Operations; Admin is the last entry.
  assert.deepEqual(Object.fromEntries(entries.filter((item) => item.adminTab).map((item) => [item.area, item.adminTab])), {
    knowledge: "knowledgeLibrary", operations: "observabilityOverview", admin: "users",
  });
  // The builder pages are part of the one Agents entry.
  assert.equal(entries.some((item) => item.area === "workflows"), false);
  assert.equal(entries.at(-1).area, "admin");
  assert.equal(getWorkspaceDestinations(false, true).some((item) => item.area === "admin"), false, "Admin only for admins");
});

test("member repository access cannot reveal operational code work through a requested or retained view", () => {
  assert.equal(codingWorkspaceView(false), "repositories");
  // Review: who manages work opens Repositories as a page of the Work menu (coding_view=repositories).
  assert.equal(codingWorkspaceView(true), "work");
});

test("the Work entry stays active on the Coding pages of the Work menu", async () => {
  const { isDestinationActive } = await import("../../src/chat/workspaceDestinations.ts");
  const work = getWorkspaceDestinations(true, true).find((item) => item.label === "Work");
  assert.equal(isDestinationActive(work, "work"), true);
  assert.equal(isDestinationActive(work, "coding"), true);
  assert.equal(isDestinationActive(work, "agents"), false);
});

test("the Agents entry stays active on the builder pages", async () => {
  const { isDestinationActive } = await import("../../src/chat/workspaceDestinations.ts");
  const agents = getWorkspaceDestinations(true, true).find((item) => item.area === "agents");
  assert.equal(isDestinationActive(agents, "agents"), true);
  assert.equal(isDestinationActive(agents, "workflows"), true);
  assert.equal(getWorkspaceDestinations(true, true).length, 6, "Chat, Knowledge, Work, Agents, Operations, Admin");
});
