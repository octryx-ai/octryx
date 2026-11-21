import { test } from "node:test";
import assert from "node:assert/strict";
import { canManageWorkWith, canReadWorkWith, visibleToReader } from "../../src/chat/work/workAccess.ts";
import { WORK_AREA_ENTRIES } from "../../src/chat/work/workAreaMenu.ts";
import { areaForRole, getWorkspaceDestinations } from "../../src/chat/workspaceDestinations.ts";

// A team leader shows the team its work. Members read Work; changing it keeps the Work role.
test("a Workspace member reads Work, only the Work role manages it", () => {
  assert.equal(canReadWorkWith(["member"], 1), true, "member of one Workspace reads");
  assert.equal(canManageWorkWith(["member"]), false, "but does not manage");
  assert.equal(canReadWorkWith([], 0), false, "no Workspace, no Work role: nothing to read");
  assert.equal(canReadWorkWith([" Operation "], 0), true);
  assert.equal(canManageWorkWith(["ADMIN"]), true);
});

test("the rail's Work opens the Work pages for every reader", () => {
  const work = (canRead) => getWorkspaceDestinations(false, canRead).find((item) => item.label === "Work");
  assert.equal(work(true).area, "work");
  assert.equal(work(false).area, "coding", "without Work access the repositories open");
});

test("a reader's Work menu leaves out the pages that configure or start work", () => {
  const shown = WORK_AREA_ENTRIES.filter((entry) => visibleToReader(entry.host, entry.key)).map((entry) => entry.key);
  for (const key of ["board", "changePlans", "runs", "epics", "repositories"]) assert.ok(shown.includes(key), key);
  for (const key of ["intake", "rules", "sessions"]) assert.ok(!shown.includes(key), key);
});

test("the rail offers a member only areas it can open; an admin area's link lands on the member's area", () => {
  const member = getWorkspaceDestinations(false, true).map((item) => item.area);
  assert.deepEqual(member, ["chat", "knowledge", "work", "agents"], "no Operations, no Admin for a member");
  const admin = getWorkspaceDestinations(true, true).map((item) => item.area);
  assert.ok(admin.includes("operations") && admin.includes("admin"));
  assert.equal(areaForRole("workflows", false), "agents", "the builder is an admin page: a member sees its Agents pages");
  assert.equal(areaForRole("operations", false), "chat");
  assert.equal(areaForRole("operations", true), "operations");
  assert.equal(areaForRole("work", false), "work");
});
