// The agent Tools setting: policy-governed tools or no tools, toolSurface on the wire.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as surface from "../../src/admin/components/agentsTab/agentToolSurface.ts";
import { buildAgentPayload, hydrateAgentFormState, resetAgentFormState } from "../../src/admin/hooks/useAdminAgentForms.helpers.ts";
import { useAdminAgentForms } from "../../src/admin/hooks/useAdminAgentForms.ts";
import { agentReadiness } from "../../src/admin/components/agentsTab/agentListModel.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function recordingSetters() {
  const values = {};
  return { values, setters: new Proxy({}, { get: (_t, name) => (value) => { values[String(name).replace(/^set/, "")] = value; } }) };
}
const text = (node) => (typeof node === "string" ? node : node.children.map(text).join(""));

test("a new agent starts with policy-governed tools; a saved agent keeps its setting", () => {
  const fresh = recordingSetters();
  resetAgentFormState(fresh.setters, "diagnosis");
  assert.equal(fresh.values.AgentFormToolSurface, "governed");
  for (const [saved, expected] of [[undefined, "governed"], ["governed", "governed"], ["none", "none"], [" none ", " none "], ["", ""], ["everything", "everything"], [null, "null"]]) {
    const { values, setters } = recordingSetters();
    hydrateAgentFormState(setters, { id: "a", name: "A", description: "", agent_type: "diagnosis", step_count: 0, is_active: true, toolSurface: saved });
    assert.equal(values.AgentFormToolSurface, expected, `saved ${saved}`);
  }
});

test("an unknown value is shown as unknown, never as governed, and is not saved back", () => {
  assert.equal(surface.toolSurfaceLabel("governed"), "Policy-governed tools");
  assert.equal(surface.toolSurfaceLabel("none"), "No tools (text only)");
  assert.equal(surface.toolSurfaceLabel("everything"), "Unknown tool setting (everything)");
  // A missing key is the documented default; an explicit null is invalid at runtime, so it is unknown.
  assert.equal(surface.toolSurfaceFromAgent({}), "governed");
  assert.equal(surface.toolSurfaceFromAgent({ toolSurface: null }), "null");
  assert.equal(surface.toolSurfaceLabel(surface.toolSurfaceFromAgent({ toolSurface: null })), "Unknown tool setting (null)");
  assert.equal(surface.toolSurfaceForSave(surface.toolSurfaceFromAgent({ toolSurface: null })).ok, false);
  // Like the backend's strict enum: padded or empty values are not trimmed into a known setting.
  for (const saved of [" none", "none ", " governed ", ""]) {
    const value = surface.toolSurfaceFromAgent({ toolSurface: saved });
    assert.equal(value, saved);
    assert.match(surface.toolSurfaceLabel(value), /^Unknown tool setting/);
    assert.equal(surface.toolSurfaceForSave(value).ok, false);
  }
  assert.equal(surface.toolSurfaceLabel(""), "Unknown tool setting (empty)");
  assert.equal(surface.toolSurfaceForSave("everything").ok, false);
  assert.equal(surface.toolSurfaceForSave("").ok, false);
  assert.deepEqual(surface.toolSurfaceForSave("none"), { ok: true, value: "none" });
});

test("the write body carries tool_surface and keeps it through unrelated edits", () => {
  const { values, setters } = recordingSetters();
  hydrateAgentFormState(setters, { id: "a", name: "A", description: "", agent_type: "diagnosis", step_count: 0, is_active: true, toolSurface: "none" });
  const payload = buildAgentPayload({
    name: "Renamed", description: values.AgentFormDescription, goal: "Add numbers", type: values.AgentFormType, thinking: "light",
    projectId: "p1", runtimeId: "", groupId: "", branchPrefix: "octryx", requireSelfReview: false,
    toolSurface: values.AgentFormToolSurface, systemPrompt: "", outputPrompt: "", setup: { capabilityCeiling: "read_only", defaultWorkflowKey: "", executionMode: "" }, preferredSkillIds: [], blockedSkillIds: [], isActive: true,
  });
  assert.equal(payload.tool_surface, "none");
  assert.equal("toolSurface" in payload, false);
  assert.equal(payload.name, "Renamed");
});

test("the conflict preview follows the server's step_needs_tools rule exactly", () => {
  const step = (name, allowedTools, stepConfig = {}, isEnabled = true) => ({ name, allowedTools, stepConfig, isEnabled });
  const steps = [
    step("Answer", []),
    step("Look up", ["read_file"]),
    step("", [], { tool_use: "required" }),
    step("Optional", [], { tool_use: "optional" }),
    step("Optional spelled", [], { tool_use: " Optional " }),
    step("Unexpected tool use", [], { tool_use: "sometimes" }),
    step("Blank tools", ["", "   "]),
    step("Null tool use", [], { tool_use: null }),
    step("Disabled", ["read_file"], {}, false),
  ];
  assert.deepEqual(surface.stepsNeedingTools(steps), ["Look up", "Step 3", "Unexpected tool use"]);
  // Like the server, a step without an enabled flag does not count.
  assert.equal(surface.stepNeedsTools({ name: "No flag", allowedTools: ["read_file"] }), false);
  assert.deepEqual(surface.stepsNeedingTools([]), []);
});

test("the No tools explanation keeps workflow participation clear", () => {
  const help = surface.TOOL_SURFACE_OPTIONS.find((option) => option.value === "none").help;
  assert.match(help, /cannot call any tool, including tool-based workflows/);
  assert.match(help, /can still run as a step in a workflow/);
});

test("the list and page facts say text-only instead of the mode's permissions", () => {
  const modes = [{ key: "diagnosis", name: "Diagnosis", capability_type: "diagnosis" }];
  const base = { id: "a", name: "A", agentType: "diagnosis", projectId: "", isActive: true };
  assert.equal(agentReadiness({ ...base, toolSurface: "none" }, modes, []).permissions, "No tools (text only)");
  assert.equal(agentReadiness({ ...base, toolSurface: "odd" }, modes, []).permissions, "Unknown tool setting (odd)");
  assert.match(agentReadiness({ ...base, toolSurface: " none" }, modes, []).permissions, /^Unknown tool setting/);
  assert.notEqual(agentReadiness(base, modes, []).permissions, "No tools (text only)");
});

function loadField() {
  const exports = {};
  const source = fs.readFileSync(new URL("../../src/admin/components/agentsTab/AgentToolSurfaceField.tsx", import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports,
    require: (name) => (name.endsWith("/agentToolSurface") ? surface : require(name)),
  });
  return exports.AgentToolSurfaceField;
}

test("the Tools field offers both choices, flags unknown values and names conflicting steps without changing them", () => {
  const Field = loadField();
  const picked = [];
  const steps = Object.freeze([Object.freeze({ id: "s1", name: "Look up", isEnabled: true, allowedTools: Object.freeze(["read_file"]), stepConfig: {} })]);
  let view;
  act(() => {
    view = TestRenderer.create(createElement(Field, { value: "governed", onChange: (value) => picked.push(value), steps }));
  });
  const radios = () => view.root.findAllByType("input");
  assert.deepEqual(radios().map((input) => [input.props.value, input.props.checked]), [["governed", true], ["none", false]]);
  assert.match(text(view.root), /Policy-governed tools/);
  assert.match(text(view.root), /No tools \(text only\)/);
  assert.equal(view.root.findAllByProps({ role: "status" }).length, 0);
  act(() => radios()[1].props.onChange());
  assert.deepEqual(picked, ["none"]);
  act(() => view.update(createElement(Field, { value: "none", onChange() {}, steps })));
  assert.match(text(view.root.findByProps({ role: "status" })), /Look up\. The server refuses No tools/);
  assert.equal(steps[0].allowedTools[0], "read_file");
  act(() => view.update(createElement(Field, { value: "everything", onChange() {}, steps: [] })));
  assert.deepEqual(radios().map((input) => input.props.checked), [false, false]);
  assert.match(text(view.root.findByProps({ role: "status" })), /“everything” is not recognised/);
  // A padded saved value selects neither choice; the author must pick one explicitly.
  act(() => view.update(createElement(Field, { value: " none", onChange() {}, steps: [] })));
  assert.deepEqual(radios().map((input) => input.props.checked), [false, false]);
  assert.equal(view.root.findAllByProps({ role: "status" }).length, 1);
  act(() => view.unmount());
});

function formArgs(overrides) {
  const calls = { requests: [], errors: [], closed: 0 };
  const noop = () => {};
  const args = new Proxy(
    {
      readJson: async (url, init) => {
        calls.requests.push({ url, init });
        if (overrides.refuse && init?.method) throw new Error(overrides.refuse);
        return url.endsWith("/meta") ? {} : init?.method ? { id: "a" } : [];
      },
      agentModes: [],
      panelAgents: [],
      editingAgent: { id: "a", name: "A" },
      agentFormName: "A", agentFormDescription: "", agentFormGoal: "", agentFormType: "diagnosis", agentFormThinking: "light",
      agentFormRuntimeId: "", agentFormGroupId: "", agentFormBranchPrefix: "octryx",
      agentFormRequireSelfReview: false, agentFormSystemPrompt: "", agentFormOutputPrompt: "",
      agentFormSetup: { capabilityCeiling: "read_only", defaultWorkflowKey: "", executionMode: "" }, agentFormPreferredSkillIds: [], agentFormBlockedSkillIds: [], agentFormActive: true,
      setAgentFormError: (value) => value && calls.errors.push(value),
      setShowAgentForm: (value) => { if (value === false) calls.closed += 1; },
      ...overrides,
    },
    { get: (target, name) => (name in target ? target[name] : noop) },
  );
  return { args, calls };
}

async function save(overrides) {
  const { args, calls } = formArgs(overrides);
  let forms;
  function Probe() {
    forms = useAdminAgentForms(args);
    return null;
  }
  act(() => { TestRenderer.create(createElement(Probe)); });
  await act(async () => { await forms.handleSaveAgent({ preventDefault() {} }); });
  return calls;
}

test("saving sends the chosen value, refuses an unknown one locally and shows a server conflict verbatim", async () => {
  const sent = await save({ agentFormToolSurface: "none" });
  const put = sent.requests.find((request) => request.init?.method === "PUT");
  assert.equal(JSON.parse(put.init.body).tool_surface, "none");

  const unknown = await save({ agentFormToolSurface: "everything" });
  assert.equal(unknown.requests.length, 0, "nothing is sent");
  assert.match(unknown.errors[0], /unknown tool setting \(everything\)/);

  const padded = await save({ agentFormToolSurface: " none" });
  assert.equal(padded.requests.length, 0, "a padded saved value is not trimmed and sent as none");

  // The backend's 409 detail is a plain string starting with this phrase (tool-surface contract).
  const conflict = "No tools (text only) conflicts with step 'Look up', which lists allowed tools.";
  const refused = await save({ agentFormToolSurface: "none", refuse: conflict });
  assert.deepEqual(refused.errors, [conflict]);
  assert.equal(refused.closed, 0, "the drawer stays open with the author's choice");
});
