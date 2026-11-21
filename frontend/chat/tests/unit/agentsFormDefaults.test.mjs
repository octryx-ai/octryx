import assert from "node:assert/strict";
import { test } from "node:test";
import {
  NEW_AGENT_DEFAULTS,
  capabilityLabel,
  resolveSafeDefaultMode,
} from "../../src/admin/hooks/useAdminAgentForms.defaults.ts";
import {
  buildAgentPayload,
  hydrateAgentFormState,
  resetAgentFormState,
} from "../../src/admin/hooks/useAdminAgentForms.helpers.ts";
import { agentReadiness } from "../../src/admin/components/agentsTab/agentListModel.ts";

const CATALOG = [
  { key: "admin", name: "Admin", capability_type: "admin", is_active: true },
  { key: "change", name: "Change", capability_type: "change", is_active: true },
  { key: "chat", name: "Chat", capability_type: "diagnosis", is_active: true },
  { key: "coding", name: "Coding", capability_type: "change", is_active: true },
  { key: "diagnosis", name: "Diagnosis", capability_type: "diagnosis", is_active: true },
  { key: "plan", name: "Plan", capability_type: "plan", is_active: true },
];

function recordingSetters() {
  const values = {};
  return {
    values,
    setters: new Proxy(
      {},
      { get: (_target, name) => (value) => { values[String(name).replace(/^set/, "")] = value; } },
    ),
  };
}

test("the default mode is the read-only diagnosis mode, never admin even when it is listed first", () => {
  assert.equal(resolveSafeDefaultMode(CATALOG), "diagnosis");
});

test("without diagnosis the first read-only mode wins; inactive and write modes never default", () => {
  const withoutDiagnosis = CATALOG.filter((mode) => mode.key !== "diagnosis");
  assert.equal(resolveSafeDefaultMode(withoutDiagnosis), "chat");
  assert.equal(
    resolveSafeDefaultMode([{ key: "plan", capability_type: "plan" }, { key: "x", capability_type: "diagnosis", is_active: false }]),
    "plan",
  );
});

test("a catalog without a read-only mode yields no preselection, so the author must choose", () => {
  assert.equal(resolveSafeDefaultMode(CATALOG.filter((mode) => ["admin", "change", "coding"].includes(mode.key))), "");
  assert.equal(resolveSafeDefaultMode([]), "");
});

test("a new agent starts inactive and with no workspace field", () => {
  const { values, setters } = recordingSetters();
  resetAgentFormState(setters, resolveSafeDefaultMode(CATALOG));
  assert.equal(values.AgentFormType, "diagnosis");
  assert.equal("AgentFormProjectId" in values, false);
  assert.equal(values.AgentFormActive, false);
  assert.equal(NEW_AGENT_DEFAULTS.isActive, false);
});

test("agents are Global: the payload never carries a project_id and hydration sets no workspace", () => {
  const { values, setters } = recordingSetters();
  hydrateAgentFormState(setters, { id: "a", name: "A", projectId: "p1", isActive: true, steps: [] });
  assert.equal("AgentFormProjectId" in values, false);
  const payload = buildAgentPayload({
    name: "A", description: "", goal: "", type: "diagnosis", thinking: "light",
    runtimeId: "", groupId: "", branchPrefix: "octryx", requireSelfReview: false, toolSurface: "governed", systemPrompt: "",
    outputPrompt: "", setup: { capabilityCeiling: "read_only", defaultWorkflowKey: "", executionMode: "" }, preferredSkillIds: [], blockedSkillIds: [], isActive: false,
  });
  assert.equal("project_id" in payload, false);
  assert.equal(payload.is_active, false);
  assert.deepEqual(Object.keys(payload).sort(), [
    "branch_prefix", "capability_ceiling", "default_workflow_key", "description", "execution_mode", "goal", "group_id",
    "is_active", "name", "output_prompt", "require_self_review", "runtime_target_id", "skill_preferences",
    "system_prompt", "thinking_level", "tool_surface",
  ]);
});

test("readiness names the mode, its permissions and the workspace", () => {
  const readiness = agentReadiness(
    { id: "1", name: "A", agentType: "admin", projectId: "p1", isActive: false, steps: [{}, {}] },
    CATALOG,
    [{ id: "p1", name: "Petclinic" }],
  );
  assert.deepEqual(readiness, {
    active: false, modeKey: "admin", modeName: "Admin", permissions: capabilityLabel("admin"), workspace: "Petclinic", stepCount: 2,
  });
  assert.equal(agentReadiness({ id: "2", name: "B", agentType: "diagnosis" }, CATALOG, []).workspace, "Global");
  assert.equal(capabilityLabel("diagnosis"), "Read-only");
});
