import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_RIGHTS, connectionLabel, detectionText, repositoryName } from "../../src/chat/coding/repository/runRepositoryModel.ts";

// Work › Repositories › "Add a repository for runs" (alpha).
test("the repository is owner/name; a pasted URL or .git is cut down, anything else says how to write it", () => {
  assert.deepEqual(repositoryName(" demo-org/demo-shop "), { name: "demo-org/demo-shop" });
  assert.deepEqual(repositoryName("https://github.com/demo-org/demo-shop.git"), { name: "demo-org/demo-shop" });
  assert.deepEqual(repositoryName("http://127.0.0.1:21944/octryx/demo-shop.git"), { name: "octryx/demo-shop" });
  for (const bad of ["demo-shop", "demo-org/../x", ""]) assert.ok("problem" in repositoryName(bad), bad);
});

test("the check says what it found: missing, apps later, no app, or the apps", () => {
  const base = { repository: "octryx/demo-shop", base_branch: "main" };
  assert.match(detectionText({ ...base, exists: false, apps: [], apps_found_at: "now" }), /no branch main/);
  assert.match(detectionText({ ...base, exists: null, apps: [], apps_found_at: "first_run" }), /first run/);
  assert.match(detectionText({ ...base, exists: true, apps: [], apps_found_at: "now" }), /test command below/);
  assert.equal(detectionText({ ...base, exists: true, apps_found_at: "now", apps: [
    { path: ".", environment_file: ".octryx/environment.json" },
    { path: "admin", environment_file: "admin/.octryx/environment.json" }] }),
  "Found 2 apps: the repository root, admin.");
});

test("rights are on by default so the work runs; a connection is named with its kind", () => {
  assert.deepEqual(DEFAULT_RIGHTS, { read: true, branch: true, write: true, pr: true });
  assert.equal(connectionLabel({ id: "1", name: "Team code", connector: "gitlab", bound_scopes: [] }), "Team code (GitLab)");
  assert.equal(connectionLabel({ id: "2", name: "GitHub (demo)", connector: "github", bound_scopes: [] }), "GitHub (demo)");
});

test("a local repository URL in the Knowledge form points to 'Add a repository for runs', https stays the rule", async () => {
  const { repositoryUrlProblem } = await import("../../src/admin/components/workspaceKnowledge/gitRepositoryScope.ts");
  assert.match(repositoryUrlProblem("http://127.0.0.1:21944/octryx/demo-shop.git"), /Add a repository for runs/);
  assert.match(repositoryUrlProblem("http://localhost:8080/x/y"), /Add a repository for runs/);
  assert.equal(repositoryUrlProblem("http://github.com/demo-org/demo-shop"), "The repository URL must use https.");
  assert.equal(repositoryUrlProblem("https://github.com/demo-org/demo-shop"), null);
});
