// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/researchPagesOneContext.test.mjs
// Research websites have one title (the page header's), and Research profiles read the one shared Workspace switch,
// no Workspace select of their own.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const read = (relative) => fs.readFileSync(path.join(SRC, relative), "utf8");

test("Research websites has one title: the page header's", () => {
  const panel = read("chat/knowledge/KnowledgeResearchSourcesPanel.tsx");
  assert.doesNotMatch(panel, /<h[1-3]>Research websites<\/h[1-3]>/);
  assert.match(panel, /aria-label="Research websites"/, "the section keeps its accessible name");
  assert.match(panel, /<AdminHeaderActions>[\s\S]*?Add website/, "the primary action sits in the page header");
});

test("Research profiles reads the shared Workspace and has no select of its own", () => {
  const assignment = read("admin/components/researchPolicies/ResearchWorkspaceAssignment.tsx");
  assert.doesNotMatch(assignment, /WorkspaceScopeSelect/);
  assert.doesNotMatch(assignment, /setSelectedProjectId/);
  assert.match(assignment, /<ChooseWorkspaceLine projects=\{projects\}/, "without one, the shared choice is asked for");
  assert.match(read("admin/hooks/useAdminResearchPolicies.ts"), /useActiveWorkspace\(projects\)/);
});
