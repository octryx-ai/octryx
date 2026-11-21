// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// The evidence-grounding policy is decided by explicit settings, edited in the admin UI.
// The Workspace states equal the backend vocabulary, an unreadable stored value shows as
// needs_configuration, and the global editor sends only the live key.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  EVIDENCE_GROUNDING_POLICY_KEY,
  EVIDENCE_GROUNDING_POLICY_STATES,
  evidenceGroundingPolicyPatch,
  evidenceGroundingPolicyState,
} from "../../src/admin/components/projectsTab/evidenceGroundingPolicy.ts";
import {
  agentTypesFromDraft,
  evidenceGroundingPatch,
  parseEvidenceGroundingSettings,
} from "../../src/admin/components/runtimeTab/evidenceGroundingSettings.ts";

const SETTINGS_SOURCE = readFileSync(
  new URL("../../../../backend/app/services/evidence_grounding_settings.py", import.meta.url),
  "utf8",
).replace(/\r\n/g, "\n");

test("the Workspace modes equal the backend vocabulary", () => {
  assert.match(SETTINGS_SOURCE, /EVIDENCE_GROUNDING_POLICY_CONFIG_KEY = "evidence_grounding_policy"/);
  const backendModes = [...SETTINGS_SOURCE.matchAll(/EVIDENCE_GROUNDING_MODE_(?!FIELD)[A-Z]+ = "([a-z]+)"/g)].map((m) => m[1]);
  const uiModes = EVIDENCE_GROUNDING_POLICY_STATES.map((entry) => entry.state).filter((state) => state !== "default");
  assert.deepEqual([...uiModes].sort(), [...backendModes].sort());
  assert.equal(EVIDENCE_GROUNDING_POLICY_KEY, "evidence_grounding_policy");
});

test("stored sections map to closed states", () => {
  assert.equal(evidenceGroundingPolicyState({}), "default");
  assert.equal(evidenceGroundingPolicyState({ evidence_grounding_policy: {} }), "default");
  assert.equal(evidenceGroundingPolicyState({ evidence_grounding_policy: { mode: "required" } }), "required");
  assert.equal(evidenceGroundingPolicyState({ evidence_grounding_policy: { mode: "workflow" } }), "workflow");
  assert.equal(evidenceGroundingPolicyState({ evidence_grounding_policy: { mode: "always" } }), "needs_configuration");
  assert.equal(evidenceGroundingPolicyState({ evidence_grounding_policy: "required" }), "needs_configuration");
});

test("the Workspace patch resets the default with null", () => {
  assert.deepEqual(evidenceGroundingPolicyPatch("required"), { evidence_grounding_policy: { mode: "required" } });
  assert.deepEqual(evidenceGroundingPolicyPatch("default"), { evidence_grounding_policy: { mode: null } });
});

test("the global editor parses the server payload and sends only the live key", () => {
  const parsed = parseEvidenceGroundingSettings({
    high_risk_agent_types: ["knowledge"],
    high_risk_agent_types_source: "configured",
    default_high_risk_agent_types: ["knowledge", "stable_jira_worker"],
  });
  assert.equal(parsed.source, "configured");
  assert.deepEqual(parsed.highRiskAgentTypes, ["knowledge"]);
  assert.deepEqual(parsed.defaultAgentTypes, ["knowledge", "stable_jira_worker"]);
  assert.deepEqual(agentTypesFromDraft("Knowledge\n stable_jira_worker , knowledge\n\n"), ["knowledge", "stable_jira_worker"]);
  assert.deepEqual(Object.keys(evidenceGroundingPatch(["knowledge"])), ["high_risk_agent_types"]);
  assert.deepEqual(evidenceGroundingPatch(null), { high_risk_agent_types: null });
});
