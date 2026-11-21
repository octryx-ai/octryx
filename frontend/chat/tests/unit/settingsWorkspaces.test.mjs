// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/settingsWorkspaces.test.mjs
//
// The Workspaces list starts on active workspaces, the overview steps come
// from payload fields only, and diagnostic codes get impact + fix.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  DEFAULT_WORKSPACE_STATUS_FILTER,
  asWorkspaceStatusFilter,
  countWorkspacesByStatus,
  filterWorkspaces,
} from "../../src/admin/components/projectsTab/workspaceListModel.ts";
import { deriveProjectNextSteps } from "../../src/admin/components/projectsTab/projectSettingsNextSteps.ts";
import { presentWorkspaceDiagnostic } from "../../src/admin/components/projectsTab/workspaceDiagnosticsPresenter.ts";

const workspaces = [
  { id: "p-1", name: "Petclinic", description: "Spring demo", is_active: true },
  { id: "p-2", name: "Archived test", description: "", is_active: false },
  { id: "p-0", name: "Default", description: "", is_active: true, is_system: true },
];

test("workspace list defaults to active and keeps the system workspace first", () => {
  assert.equal(DEFAULT_WORKSPACE_STATUS_FILTER, "active");
  const active = filterWorkspaces(workspaces, "", DEFAULT_WORKSPACE_STATUS_FILTER);
  assert.deepEqual(active.map((item) => item.id), ["p-0", "p-1"]);
  assert.deepEqual(filterWorkspaces(workspaces, "", "inactive").map((item) => item.id), ["p-2"]);
  assert.equal(filterWorkspaces(workspaces, "", "all").length, 3);
  assert.deepEqual(countWorkspacesByStatus(workspaces), { active: 2, inactive: 1, all: 3 });
});

test("workspace search matches name, description and id case-insensitively", () => {
  assert.deepEqual(filterWorkspaces(workspaces, "SPRING", "all").map((item) => item.id), ["p-1"]);
  assert.deepEqual(filterWorkspaces(workspaces, "p-2", "all").map((item) => item.id), ["p-2"]);
  assert.equal(asWorkspaceStatusFilter("bogus"), "active");
  assert.equal(filterWorkspaces(null, "", "all").length, 0);
});

test("next steps are derived from payload fields only; design steps left with Design quality", () => {
  const steps = deriveProjectNextSteps({
    id: "p-1",
    name: "Petclinic",
    description: "",
    is_active: true,
    code_repositories: [],
    design_readiness: { missing_required_kinds: ["outcome_brief", "prd"], pending_required_kinds: [] },
    design_traceability: { blockers: ["No artifact is linked to a project task."] },
  });
  assert.deepEqual(steps.map((step) => step.section), ["repositories"]);
  const done = deriveProjectNextSteps({
    id: "p-2",
    name: "Done",
    description: "",
    is_active: true,
    code_repositories: [{ id: "r" }],
  });
  assert.deepEqual(done, [], "zero agent-template installations never produce a workflow step");
});

test("the repository step is for Coding and names the Knowledge repositories that could become code repositories", () => {
  const project = { id: "p-3", name: "Docs only", description: "", is_active: true, code_repositories: [] };
  const [withKnowledge] = deriveProjectNextSteps(project, 2);
  assert.equal(withKnowledge.title, "Add a code repository for Coding");
  assert.match(withKnowledge.detail, /2 Knowledge repositories can be added as code repositories/);
  assert.match(withKnowledge.detail, /Skip this if the Workspace does not use Coding\./);
  assert.match(deriveProjectNextSteps(project, 1)[0].detail, /1 Knowledge repository can be added as a code repository\./);
  assert.doesNotMatch(deriveProjectNextSteps(project, null)[0].detail, /Knowledge/);
});

test("diagnostic codes become impact and fix, honouring the runtime access mode", () => {
  const allInstalled = presentWorkspaceDiagnostic(
    { code: "missing-runtime-binding", severity: "error", message: "Workspace has no enabled runtime binding." },
    "all_installed",
  );
  assert.match(allInstalled.impact, /still run/);
  assert.equal(allInstalled.fixSection, "models", "the fix opens the Models section");
  assert.equal(allInstalled.code, "missing-runtime-binding");
  const selectedOnly = presentWorkspaceDiagnostic(
    { code: "missing-runtime-binding", severity: "error", message: "" },
    "selected_only",
  );
  assert.match(selectedOnly.impact, /cannot start/);
  const unknown = presentWorkspaceDiagnostic({ code: "x-y", severity: "warning", message: "Raw." }, "all_installed");
  assert.equal(unknown.fixSection, null);
  assert.equal(unknown.impact, "Raw.");
});

test("a new Workspace's setup runs in order and ticks only what a loaded fact proves", async () => {
  const { deriveWorkspaceSetupSteps } = await import("../../src/admin/components/projectsTab/projectSettingsNextSteps.ts");
  const fresh = deriveWorkspaceSetupSteps({ accessEntries: 1, connectors: 0, syncedSources: 0, allowedModels: null });
  assert.deepEqual(fresh.map((step) => step.section), ["access", "connectors", "knowledge", "models", "agents"]);
  assert.deepEqual(fresh.map((step) => step.state), ["done", "open", "open", "unknown", "unknown"]);
  const ready = deriveWorkspaceSetupSteps({ accessEntries: 3, connectors: 2, syncedSources: 1, allowedModels: 2 });
  assert.deepEqual(ready.slice(0, 4).map((step) => step.state), ["done", "done", "done", "done"]);
});
