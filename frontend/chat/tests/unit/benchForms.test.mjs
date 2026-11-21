// The benchmark settings in the UI: browser and research phases (PUT …/device-runs, a
// one-key patch), the Work item's cost budget (PUT …/limits replaces the item's limits; the cascade is the client's)
// and the run start's Model select (runtime_target.model, device targets only).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  browserPhaseProblem,
  browserPhasesPatch,
  minSourcesValue,
  readRunPhaseSettings,
  researchMinSourcesPatch,
  researchPhasesPatch,
  runPhaseSaveError,
} from "../../src/chat/devices/runPhaseSettingsModel.ts";
import {
  budgetWithCost,
  cascades,
  childItems,
  childLimitsBody,
  costBudgetValue,
  limitsBody,
  limitsSaveError,
  readItemLimits,
} from "../../src/chat/work/workItemLimitsModel.ts";
import {
  CODEX_SEAT_MODELS,
  engineRouteLine,
  modelOptions,
  modelSource,
  modelStartError,
  targetWithModel,
} from "../../src/chat/workflowRun/runModelModel.ts";

const section = { project_id: "ws-1", can_edit: true, browser_phases: ["epic-delivery.implement"] };

test("browser phases: the server's pattern and limits decide; the patch names only browser_phases", () => {
  const current = readRunPhaseSettings(section).browserPhases;
  assert.equal(browserPhaseProblem(" epic-delivery.verify ", current), null);
  assert.match(browserPhaseProblem("implement", current), /<workflow>\.<phase>/);
  assert.match(browserPhaseProblem("-bad.x", current), /<workflow>\.<phase>/);
  assert.match(browserPhaseProblem("epic-delivery.implement", current), /already listed/);
  assert.match(browserPhaseProblem(`a.${"x".repeat(120)}`, current), /120 characters/);
  assert.match(browserPhaseProblem("a.b", Array.from({ length: 20 }, (_, i) => `w.p${i}`)), /At most 20/);
  assert.deepEqual(browserPhasesPatch([...current, "a.b"]), { browser_phases: ["epic-delivery.implement", "a.b"] });
});

test("device-run refusals read as words at the field", () => {
  assert.match(runPhaseSaveError({ status: 400, code: "invalid_browser_phases" }), /<workflow>\.<phase>/);
  assert.match(runPhaseSaveError({ status: 403, code: null }), /admins and owners/);
  assert.match(runPhaseSaveError({ status: 404, code: "workspace_not_found" }), /no longer exists/);
  assert.match(runPhaseSaveError({ status: 500 }), /could not be saved/);
});

test("cost budget: the body keeps the loop limit and other budget keys; empty clears only cost_usd", () => {
  const stored = readItemLimits({ run_limits: { loop_limit: 3, budget: { tokens: 50000, cost_usd: 4 } } });
  assert.deepEqual(limitsBody(3, budgetWithCost(stored.budget, 12.5)),
    { loop_limit: 3, budget: { tokens: 50000, cost_usd: 12.5 } });
  assert.deepEqual(limitsBody(3, budgetWithCost(stored.budget, null)), { loop_limit: 3, budget: { tokens: 50000 } });
  assert.deepEqual(limitsBody(null, budgetWithCost({ cost_usd: 4 }, null)), {}, "an empty body clears the item's limits");
  assert.deepEqual(costBudgetValue(""), { value: null });
  assert.deepEqual(costBudgetValue("12,50"), { value: 12.5 });
  assert.ok("error" in costBudgetValue("0"));
  assert.ok("error" in costBudgetValue("1.234"));
  assert.ok("error" in costBudgetValue("abc"));
});

test("cascade: an epic's stories and their sub-items, each keeping its own loop limit", () => {
  const item = (id, key, extra = {}) => ({ id, source_key: key, title: key, ...extra });
  const epic = item("e", "OCX-1", { issue_type: "Epic" });
  const items = [epic, item("s1", "OCX-2", { epic_key: "OCX-1" }), item("t1", "OCX-4", { parent_key: "OCX-2" }),
    item("s2", "OCX-3", { epic_key: "OCX-1" }), item("x", "OCX-9", { epic_key: "OCX-8" })];
  assert.deepEqual(childItems(epic, items).map((child) => child.id).sort(), ["s1", "s2", "t1"]);
  assert.equal(cascades(epic), true);
  assert.equal(cascades({ issue_type: "Story" }), true);
  assert.equal(cascades({ issue_type: "Task" }), false);
  const child = readItemLimits({ run_limits: { loop_limit: 2 } });
  assert.deepEqual(childLimitsBody(child, 5), { loop_limit: 2, budget: { cost_usd: 5 } });
});

test("limits refusals read as words", () => {
  assert.match(limitsSaveError({ status: 422, code: "invalid_run_limits" }), /amount above 0/);
  assert.match(limitsSaveError({ status: 403, code: "work_item_scope" }), /not a member/);
  assert.match(limitsSaveError({ status: 404, code: "unknown_work_item" }), /no longer exists/);
});

const device = (profile) => ({ kind: "device", device_id: "d1", folder: "/src/app", profile });

test("model options per engine and route; Automatic first and sends no model", () => {
  const rows = { profile: "seat", reason: null, models: [{ id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" }] };
  assert.deepEqual(modelSource("claude_code", device("seat")), { kind: "server", profile: "seat", deviceId: "d1" });
  assert.deepEqual(modelSource("codex", device("governed")), { kind: "server", profile: "governed", deviceId: "d1" });
  assert.deepEqual(modelSource("codex", device("seat")), { kind: "codex_seat" });
  assert.equal(modelSource("claude_code", { kind: "auto" }).kind, "none");
  assert.deepEqual(modelOptions(modelSource("claude_code", device("seat")), rows).map((o) => o.label),
    ["Automatic", "Claude Sonnet 5.5"]);
  assert.deepEqual(modelOptions({ kind: "codex_seat" }, null).map((o) => o.value), ["", ...CODEX_SEAT_MODELS]);
  assert.equal(engineRouteLine("codex", device("seat")), "Codex · Own subscription");
  assert.equal(engineRouteLine("claude_code", device("governed")), "Claude Code · Company model");
  assert.deepEqual(targetWithModel(device("seat"), "gpt-6-luna"), { ...device("seat"), model: "gpt-6-luna" });
  assert.deepEqual(targetWithModel({ ...device("seat"), model: "x" }, ""), device("seat"));
  assert.deepEqual(targetWithModel({ kind: "auto" }, "gpt-6-luna"), { kind: "auto" });
  assert.match(modelStartError({ code: "device_model_not_allowed" }), /not allowed for this route/);
  assert.equal(modelStartError({ code: "workflow_not_found" }), null);
});

test("research phases: same rule as browser phases, own patch key, own refusal; min sources 1..20, default 3", () => {
  assert.equal(readRunPhaseSettings(section).researchMinSources, 3);
  assert.deepEqual(readRunPhaseSettings(section).researchPhases, []);
  const stored = readRunPhaseSettings({ ...section, research_phases: ["spec-writing.draft"], research_min_sources: 5 });
  assert.deepEqual(stored.researchPhases, ["spec-writing.draft"]);
  assert.equal(stored.researchMinSources, 5);
  assert.match(browserPhaseProblem("draft", stored.researchPhases, "spec-writing.draft"), /for example spec-writing\.draft/);
  assert.match(browserPhaseProblem("spec-writing.draft", stored.researchPhases), /already listed/);
  assert.deepEqual(researchPhasesPatch(["spec-writing.draft"]), { research_phases: ["spec-writing.draft"] });
  assert.deepEqual(researchMinSourcesPatch(4), { research_min_sources: 4 });
  assert.deepEqual(minSourcesValue(" 20 "), { value: 20 });
  for (const bad of ["0", "21", "2.5", "", "-1"]) assert.match(minSourcesValue(bad).problem, /1 to 20/);
  const path = "agent_gateway_policy.device_runs";
  assert.match(runPhaseSaveError({ status: 400, code: "invalid_research_phases", path: `${path}.research_phases` }),
    /research phase is <workflow>\.<phase>/);
  assert.match(runPhaseSaveError({ status: 400, code: "invalid_number", path: `${path}.research_min_sources` }),
    /Minimum sources is a whole number from 1 to 20/);
});
