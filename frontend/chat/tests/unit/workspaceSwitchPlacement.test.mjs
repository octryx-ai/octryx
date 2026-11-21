// One Workspace context for the whole app. The one switch sits at the head of the rail (and in the
// compact menu bar on narrow screens); Workspace-scoped pages carry no switch of their own and read the one shared
// choice (chat/useActiveWorkspace), so switching once switches every area.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const source = (file) => readFileSync(new URL(`../../src/${file}`, import.meta.url), "utf8");
const SCOPED = [
  "chat/work/WorkAreaWorkspace.tsx",
  "chat/coding/CodingAreaWorkspace.tsx",
  "chat/coding/CodingWorkspaceEntry.tsx",
  "chat/agents/AgentsAreaWorkspace.tsx",
  "chat/knowledge/KnowledgeAreaWorkspace.tsx",
  "chat/setup/SetupGuidePage.tsx",
  "admin/components/workspaceKnowledge/AdminWorkspaceKnowledgeTab.tsx",
  "admin/components/workspaceKnowledge/KnowledgeAdminPage.tsx",
];

test("Workspace-scoped pages render no switch of their own and read the shared choice", () => {
  for (const file of SCOPED) {
    const text = source(file);
    assert.doesNotMatch(text, /<WorkspaceScopeSelect\b[^>]*variant="header"/, `${file} has no page switch`);
    assert.match(text, /useActiveWorkspace\(/, `${file} reads the shared choice`);
  }
});

test("the one switch sits at the head of the rail and in the compact menu", () => {
  const rail = source("chat/AreaRail.tsx");
  assert.match(rail, /<CompanionLogoTrigger[\s\S]*?\/>\s*<GlobalWorkspaceSwitch /, "right below the logo");
  assert.match(source("chat/CompactAreaMenu.tsx"), /<GlobalWorkspaceSwitch variant="compact"/);
  const view = source("chat/AppContainerView.tsx");
  assert.equal((view.match(/projects=\{chatState\?\.projects\} fallbackWorkspaceId=\{chatState\?\.selectedProjectId\}/g) ?? []).length, 2);
});
