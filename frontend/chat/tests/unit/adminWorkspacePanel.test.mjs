// Admin › Workspaces — a row opens the Workspace's essentials in a side panel, read from today's
// endpoints (access, Knowledge sources, the Workspace's connections). The overview page (GET .../overview, 404 until
// the central configuration is served) is gone, so no 404 is called.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

import { connectionsText, membersText, sourcesText } from "../../src/admin/components/projectsTab/workspaceGlance.ts";

const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");

test("the panel's facts read as short lines; an endpoint that did not answer shows a dash", () => {
  assert.equal(membersText({
    assignments: [{ project_role: "owner" }, { project_role: "member" }, { project_roles: ["member"], project_role: "viewer" }],
    group_assignments: [{ group: "g1" }],
  }), "3 people · 1 Owner, 2 Member · 1 group");
  assert.equal(membersText({ assignments: [] }), "0 people");
  assert.equal(membersText(null), "—");
  assert.equal(sourcesText([{ last_run: { state: "completed" } }, { state: "paused", last_run: null }]), "2 sources · 1 synced · 1 paused");
  assert.equal(sourcesText([]), "No sources yet");
  assert.equal(sourcesText(null), "—");
  assert.equal(connectionsText([{ name: "Jira Cloud" }, { type: "bitbucket" }]), "2 available: Jira Cloud, bitbucket");
  assert.equal(connectionsText([]), "None available");
  assert.equal(connectionsText(null), "—");
});

test("a row opens the side panel; nothing calls a workspace overview", () => {
  const tab = fs.readFileSync(path.join(SRC, "admin/components/AdminProjectsTab.tsx"), "utf8");
  assert.match(tab, /<WorkspaceSidePanel /);
  assert.doesNotMatch(tab, /WorkspacePage\b/);
  const panel = fs.readFileSync(path.join(SRC, "admin/components/projectsTab/WorkspaceSidePanel.tsx"), "utf8");
  assert.match(panel, /<SidePanel/);
  assert.match(panel, /\/access`/);
  assert.match(panel, /\/api\/v1\/workspaces\/\$\{id\}\/connections/);
  assert.match(panel, /admin-panel__action-btn--primary[^>]*onClick=\{onOpenSettings\}/s);
  const walk = (dir) => fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
    entry.isDirectory() ? walk(path.join(dir, entry.name)) : [path.join(dir, entry.name)]);
  for (const file of walk(path.join(SRC, "admin")).filter((name) => /\.tsx?$/.test(name))) {
    assert.doesNotMatch(fs.readFileSync(file, "utf8"), /\/overview`/, `${file} calls the overview`);
  }
});
