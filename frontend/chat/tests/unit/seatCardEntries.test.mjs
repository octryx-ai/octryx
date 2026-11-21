// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/seatCardEntries.test.mjs
// Seat-card finding: admins could not find the Workspace seat card. Every entry to it must resolve to the
// one Agents view (`agents_view=classification`), and the card carries "Seats" in its name.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

import { AGENTS_AREA_ENTRIES } from "../../src/chat/agents/agentsAreaMenu.ts";
import { SEAT_CARD_LABEL, readUrlAgentsView, seatCardHref } from "../../src/chat/agents/agentsFocus.ts";
import { readUrlWorkspaceSection, workspaceSectionHref } from "../../src/admin/components/projectsTab/workspaceSettingsLink.ts";
import { resolveAdminAreaTab } from "../../src/admin/config/adminPanelAreas.ts";

const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const source = (relative) => fs.readFileSync(path.join(SRC, relative), "utf8");

test("the seat card's one address opens the classification view of that Workspace", () => {
  const href = seatCardHref("ws 1");
  const search = href.slice(href.indexOf("?"));
  assert.equal(readUrlAgentsView(search), "classification");
  const params = new URLSearchParams(search);
  assert.deepEqual([params.get("area"), params.get("workspace_id")], ["agents", "ws 1"]);
  assert.match(SEAT_CARD_LABEL, /^Seats/);
});

test("the Agents menu lists the seat card and Policy under Governance", () => {
  const governance = AGENTS_AREA_ENTRIES.filter((entry) => entry.group === "Governance");
  assert.deepEqual(governance.map((entry) => [entry.host, entry.host === "agents" ? entry.key : entry.tab, entry.label]),
    [["agents", "classification", SEAT_CARD_LABEL], ["agents", "policy", "Policy"]]);
});

test("Workspace overview, Coding engine pointer and the platform matrix all lead to the seat card", () => {
  assert.match(source("admin/components/projectsTab/ProjectSettingsOverview.tsx"),
    /href=\{workspaceSectionHref\(project\.id, "classification"\)\} data-testid="workspace-seat-card-link">\{SEAT_CARD_LABEL\}/);
  assert.match(source("chat/engines/EngineCards.tsx"), /href=\{seatCardHref\(projectId\)\} data-testid="engine-codex-seat-link"/);
  const matrix = source("admin/components/dataClassification/AdminClassificationPolicy.tsx");
  assert.match(matrix, /data-testid="classification-workspace-seats-hint"/);
  assert.match(matrix, /onClick=\{\(\) => openAdminTab\("projects"\)\}>Workspace<\/button>/);
  assert.match(source("admin/components/dataClassification/WorkspaceDataClassificationCard.tsx"), /aria-label=\{SEAT_CARD_LABEL\}/);
});

test("a Workspace detail deep link opens the named section; classification is Rules with the card on top", () => {
  const href = workspaceSectionHref("ws 1", "classification");
  assert.equal(href, "/chat?area=admin&tab=projects&workspace_id=ws+1&section=classification");
  assert.equal(resolveAdminAreaTab("admin", "projects"), "projects");
  const read = (section) => readUrlWorkspaceSection(`?area=admin&tab=projects&workspace_id=ws-1&section=${section}`);
  assert.deepEqual(read("classification"), { workspaceId: "ws-1", section: "rules", focus: "classification" });
  for (const section of ["coding", "rules", "models"]) assert.deepEqual(read(section), { workspaceId: "ws-1", section, focus: null });
  assert.deepEqual(read("nonsense"), { workspaceId: "ws-1", section: "overview", focus: null });
  assert.equal(readUrlWorkspaceSection("?area=admin&tab=projects&workspace_id=ws-1"), null, "no section: no request");
});
