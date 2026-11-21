// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codingEngine.test.mjs
//
// Coding engine (Claude Code or Codex): what applies to a person and why, which choices are open to them,
// the bodies the three settings send ("platform default" / "Workspace default" are null), and refusals at the field.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  allowedProblem,
  effectiveLine,
  engineLabel,
  engineSaveErrors,
  notAllowedNotice,
  personalEngineBody,
  personalOptions,
  personalValue,
  platformDefaultHint,
  readWorkspaceEngines,
  toggleAllowed,
  workspaceDefaultOptions,
  workspaceEnginesBody,
} from "../../src/chat/engines/engineModel.ts";
import { readJob } from "../../src/chat/devices/deviceJobsModel.ts";
import { auditChangeLabel } from "../../src/admin/components/observability/auditModel.ts";

// The server's answer for a member whose stored Codex choice is not allowed in a Claude-Code-only Workspace.
const restricted = {
  project_id: "ws1",
  engines: ["claude_code", "codex"],
  workspace: { allowed: ["claude_code"], default: null },
  source: "workspace",
  effective: { engine: "claude_code", source: "workspace", allowed: ["claude_code"], workspace_default: "claude_code",
    platform_default: "codex", person_choice: "codex" },
  can_edit: false,
};

test("a job without an engine runs on Claude Code; ids are never shown raw", () => {
  assert.equal(engineLabel(null), "Claude Code");
  assert.equal(engineLabel("codex"), "Codex");
  assert.equal(engineLabel("gemini_cli"), "Gemini cli");
  assert.equal(readJob({ id: "j1", engine: null }).engine, null);
  assert.equal(readJob({ id: "j1" }, { ...readJob({ id: "j1", engine: "codex" }) }).engine, "codex",
    "an update without the field keeps the engine the job started with");
});

test("what applies to you says where it comes from", () => {
  const answer = readWorkspaceEngines(restricted);
  assert.equal(effectiveLine(answer.effective), "You use: Claude Code (Workspace default)");
  assert.equal(effectiveLine({ ...answer.effective, engine: "codex", source: "person" }), "You use: Codex (your choice)");
  assert.equal(effectiveLine({ ...answer.effective, source: "platform" }), "You use: Claude Code (platform default)");
});

test("a stored choice the Workspace does not allow shows the notice; one that counts does not", () => {
  const { effective } = readWorkspaceEngines(restricted);
  assert.equal(notAllowedNotice(effective),
    "Your choice Codex is not allowed in this Workspace; the Workspace default applies.");
  assert.equal(notAllowedNotice({ ...effective, engine: "codex", source: "person", allowed: ["claude_code", "codex"] }), null);
  assert.equal(notAllowedNotice({ ...effective, personChoice: null }), null);
});

test("a person chooses only among allowed engines; the stored but not allowed choice is not preselected", () => {
  const { effective } = readWorkspaceEngines(restricted);
  assert.deepEqual(personalOptions(effective).map((o) => [o.value, o.label, o.disabled, o.hint ?? null]), [
    ["", "Workspace default (Claude Code)", false, null],
    ["claude_code", "Claude Code", false, null],
    ["codex", "Codex", true, "Not allowed in this Workspace"],
  ]);
  assert.equal(personalValue(effective), "");
  assert.equal(personalValue({ ...effective, source: "person", personChoice: "claude_code" }), "claude_code");
});

test("the Workspace default offers the platform default and the allowed engines only", () => {
  assert.deepEqual(workspaceDefaultOptions(["codex"], "claude_code").map((o) => [o.value, o.label]),
    [["", "Platform default (Claude Code)"], ["codex", "Codex"]]);
  assert.equal(platformDefaultHint(["codex"], "claude_code"), 'Claude Code is not allowed here, so "Platform default" means Codex.');
  assert.equal(platformDefaultHint(["claude_code", "codex"], "claude_code"), null);
});

test("clearing an engine keeps the order, drops a default that is no longer allowed, and one must stay", () => {
  const draft = { allowed: ["claude_code", "codex"], default: "codex" };
  assert.deepEqual(toggleAllowed(draft, "codex", false), { allowed: ["claude_code"], default: "" });
  assert.deepEqual(toggleAllowed({ allowed: ["codex"], default: "" }, "claude_code", true), { allowed: ["claude_code", "codex"], default: "" });
  assert.equal(allowedProblem(toggleAllowed({ allowed: ["codex"], default: "" }, "codex", false).allowed), "Allow at least one engine.");
});

test("Platform default and Workspace default are sent as null", () => {
  assert.deepEqual(workspaceEnginesBody({ allowed: ["claude_code"], default: "" }), { allowed: ["claude_code"], default: null });
  assert.deepEqual(workspaceEnginesBody({ allowed: ["codex"], default: "codex" }), { allowed: ["codex"], default: "codex" });
  assert.deepEqual(personalEngineBody(""), { engine: null });
  assert.deepEqual(personalEngineBody("codex"), { engine: "codex" });
});

test("422 codes read as words at their field; the policy error and other statuses are general", () => {
  const refuse = (code, field) => ({ detail: { errors: [{ code, field }] } });
  assert.deepEqual(engineSaveErrors(422, refuse("allowed_must_name_an_engine", "agent_gateway_policy.engines.allowed")),
    { allowed: "Allow at least one engine." });
  assert.deepEqual(engineSaveErrors(422, refuse("engine_unknown", "agent_gateway_policy.engines.allowed[1]")),
    { allowed: "Choose Claude Code or Codex." });
  assert.deepEqual(engineSaveErrors(422, refuse("duplicate_engine", "agent_gateway_policy.engines.allowed")),
    { allowed: "Each engine can be allowed only once." });
  assert.deepEqual(engineSaveErrors(422, refuse("default_not_allowed", "agent_gateway_policy.engines.default")),
    { default: "The default must be one of the allowed engines." });
  assert.deepEqual(engineSaveErrors(422, refuse("engine_not_allowed_in_workspace", "engine")),
    { engine: "This engine is not allowed in this Workspace." });
  assert.match(engineSaveErrors(422, refuse("agent_gateway_policy_invalid", "agent_gateway_policy.tool_rules[0]")).general,
    /^Not saved: The Workspace's coding-tool policy/);
  assert.deepEqual(engineSaveErrors(403, null, "platform"), { general: "Not saved: only platform admins can change the platform default." });
  assert.deepEqual(engineSaveErrors(404, null), { general: "Not saved: this Workspace was not found, or you are not a member." });
});

test("an answer that is not an engine setting is not read", () => {
  assert.equal(readWorkspaceEngines({ workspace: { allowed: [] }, effective: { engine: "codex" } }), null);
  assert.equal(readWorkspaceEngines(null), null);
});

test("the three audited changes read as words in Admin › Audit", () => {
  assert.equal(auditChangeLabel("admin.agent_gateway.default_engine_updated"), "Platform coding engine changed");
  assert.equal(auditChangeLabel("admin.agent_gateway.engines_updated"), "Workspace coding engines changed");
  assert.equal(auditChangeLabel("user.agent_engine_updated"), "Personal coding engine changed");
});
