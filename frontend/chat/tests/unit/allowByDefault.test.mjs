// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/allowByDefault.test.mjs
//
// Allow by default (backend device_runs.tool_defaults, POST …/device-runs/remedy,
// `tool_allowed_by_default` run events, seat_policy.default_seat_mode): the tool-defaults view and PUT body, the
// refusal's remedy and its texts, the run history rows and count, and the seat state people see.

import assert from "node:assert/strict";
import test from "node:test";

import {
  allowedToolProblem, readToolDefaults, showsAllowedTools, toolDefaultsErrorField, toolDefaultsErrorText,
  toolDefaultsPatch,
} from "../../src/chat/devices/toolDefaultsModel.ts";
import {
  readRemedy, remedyBody, remedyChangeText, remedyDoneText, remedyErrorText, remedyOfResult,
} from "../../src/chat/devices/remedyModel.ts";
import { allowedByDefaultCountText } from "../../src/chat/workflowRun/allowedByDefaultModel.ts";
import { applyJobEvent, readJobs } from "../../src/chat/devices/deviceJobsModel.ts";
import { turnView } from "../../src/chat/devices/deviceTurnView.ts";
import { runHistory } from "../../src/chat/workflowRun/runHistoryModel.ts";
import { foldDeviceToolSteps, foldToolSteps } from "../../src/chat/toolStepFoldModel.ts";
import { seatStateView } from "../../src/admin/components/dataClassification/seatStateModel.ts";
import { seatRules } from "../../src/mobile/engineSeatModel.ts";

const payload = (effective, extra = {}) => ({ project_id: "ws-1", can_edit: true, tool_defaults_effective: effective, ...extra });

test("tool defaults: the effective values, defaults for anything unknown, nothing for unreported keys", () => {
  const view = readToolDefaults(payload({ unknown_tools: "deny", web_tools: "sometimes", allowed_tools: ["web.run", 3] }));
  assert.equal(view.effective.unknown_tools, "deny");
  assert.equal(view.effective.web_tools, "all", "a value this UI does not know falls back to the default");
  assert.equal(view.effective.network, "open");
  assert.deepEqual(view.effective.allowed_tools, ["web.run"]);
  assert.equal(showsAllowedTools(view.effective), true);
  assert.equal(readToolDefaults({ project_id: "ws-1", can_edit: true }), null, "no tool_defaults_effective: no section");
});

test("tool defaults PUT: only the changed key (the server merges); back at the default or an empty list is null", () => {
  assert.deepEqual(toolDefaultsPatch({ network: "allowlist" }), { tool_defaults: { network: "allowlist" } });
  assert.deepEqual(toolDefaultsPatch({ web_tools: "all" }), { tool_defaults: { web_tools: null } });
  assert.deepEqual(toolDefaultsPatch({ allowed_tools: ["web.run"] }), { tool_defaults: { allowed_tools: ["web.run"] } });
  assert.deepEqual(toolDefaultsPatch({ allowed_tools: [] }), { tool_defaults: { allowed_tools: null } });
});

test("allowed tools: the server's limits in words before anything is sent", () => {
  assert.match(allowedToolProblem("  ", []), /Enter a tool name/);
  assert.match(allowedToolProblem("x".repeat(201), []), /at most 200 characters/);
  assert.match(allowedToolProblem("web.run", ["web.run"]), /already listed/);
  assert.match(allowedToolProblem("b", Array.from({ length: 100 }, (_, i) => `t${i}`)), /At most 100 tools/);
  assert.equal(allowedToolProblem("spawn_agent", ["web.run"]), null);
});

test("tool defaults errors: each 400 reason lands at its field in words", () => {
  const one = { status: 400, code: "invalid_tool_default", path: "agent_gateway_policy.device_runs.tool_defaults.shell" };
  assert.equal(toolDefaultsErrorField(one), "shell");
  assert.match(toolDefaultsErrorText(one), /does not know this value/);
  const list = { status: 400, code: "invalid_allowed_tools", path: "x.tool_defaults.allowed_tools" };
  assert.equal(toolDefaultsErrorField(list), "allowed_tools");
  assert.match(toolDefaultsErrorText(list), /1 to 200 characters/);
  assert.equal(toolDefaultsErrorField({ status: 400, code: "invalid_tool_defaults", path: "x.tool_defaults" }), "section");
  assert.match(toolDefaultsErrorText({ status: 403, code: null }), /admins and owners/);
});

test("remedy: read from a refusal's result (object or JSON text); one this UI cannot apply is ignored", () => {
  const unknown = { setting: "device_runs.tool_defaults.allowed_tools", value: ["web.run"], tool: "web.run" };
  assert.deepEqual(remedyOfResult({ decision: "deny", remedy: unknown }),
    { setting: unknown.setting, key: "allowed_tools", value: ["web.run"], tool: "web.run" });
  assert.equal(remedyOfResult(JSON.stringify({ remedy: unknown })).tool, "web.run");
  assert.equal(readRemedy({ setting: "device_runs.tool_defaults.allowed_tools", value: [] }), null, "no tool to add");
  assert.equal(readRemedy({ setting: "device_runs.tool_defaults.secrets", value: "allow" }), null);
  assert.equal(readRemedy({ setting: "seat_mode", value: "allowed" }), null);
});

test("remedy: the confirmation names the setting and value or the tool; the POST body is the remedy as given", () => {
  const web = readRemedy({ setting: "device_runs.tool_defaults.web_tools", value: "all" });
  assert.equal(remedyChangeText(web), "Sets “Web search and fetch” to “Every phase” for this Workspace.");
  assert.deepEqual(remedyBody(web), { setting: "device_runs.tool_defaults.web_tools", value: "all" });
  const tool = readRemedy({ setting: "device_runs.tool_defaults.allowed_tools", value: ["web.run"], tool: "web.run" });
  assert.match(remedyChangeText(tool), /Adds “web\.run” to the tools allowed/);
  assert.deepEqual(remedyBody(tool), { setting: "device_runs.tool_defaults.allowed_tools", value: ["web.run"], tool: "web.run" });
  assert.match(remedyDoneText(tool), /“web\.run” is allowed in this Workspace\. It applies to the next tool call/);
  assert.match(remedyErrorText({ status: 403, code: "workspace_admin_required" }), /Only the Workspace's admins/);
  assert.match(remedyErrorText({ status: 400, code: "remedy_invalid" }), /does not know this setting/);
  assert.match(remedyErrorText({ status: 400, code: "remedy_tool_missing" }), /did not name the tool/);
  assert.match(remedyErrorText({ status: 404, code: null }), /no longer exists/);
});

test("refused tool steps carry their remedy into the fold, in chat (denied ToolCall row) and in a device job", () => {
  const remedy = { setting: "device_runs.tool_defaults.allowed_tools", value: ["web.run"], tool: "web.run" };
  const chat = foldToolSteps([{ id: "c1", toolName: "web.run", parameters: {}, status: "denied_by_policy",
    result: { decision: "deny", state: "denied", reason: "unclassified_tool", remedy }, createdAt: null }]);
  assert.equal(chat.failures.length, 1);
  assert.equal(chat.failures[0].blocked, true);
  assert.equal(chat.failures[0].remedy.tool, "web.run");
  const device = foldDeviceToolSteps([{ key: "u1", tool: "WebSearch", status: "error",
    output: "Octryx policy denied this tool call [rule outside-phase-tools] (outside_phase_tools): This Workspace does not use the web in its runs.",
    remedy: readRemedy({ setting: "device_runs.tool_defaults.web_tools", value: "all" }) }]);
  assert.match(device.failures[0].text, /WebSearch blocked by the workspace rules: This Workspace does not use the web/);
  assert.equal(device.failures[0].remedy.key, "web_tools");
});

const event = (id, kind, detail) => ({ id, kind, node_id: null, detail, actor_id: null, created_at: null });

test("run history: quiet 'Allowed by default' rows, equal calls in a row folded; the summary count", () => {
  const web = { tool: "WebSearch", setting: "tool_defaults.web_tools", session_id: "s" };
  const events = [event("1", "run_started", {}), event("2", "tool_allowed_by_default", web),
    event("3", "tool_allowed_by_default", web), event("4", "tool_allowed_by_default", { tool: "spawn_agent", setting: "tool_defaults.unknown_tools" }),
    event("5", "tool_allowed_by_default", web)];
  const rows = runHistory(events, []).map((row) => [row.title, row.text, row.quiet ?? false]);
  assert.deepEqual(rows, [
    ["Run", "started", false],
    ["Allowed by default", "WebSearch (web search and fetch) · 2 times", true],
    ["Allowed by default", "spawn_agent (tools without a rule)", true],
    ["Allowed by default", "WebSearch (web search and fetch)", true],
  ]);
  const edits = runHistory([event("a", "tool_allowed_by_default", { tool: "Edit", setting: "tool_defaults.path_rules", path: "src/a.ts" }),
    event("b", "tool_allowed_by_default", { tool: "Edit", setting: "tool_defaults.path_rules", path: "src/b.ts" })], []);
  assert.deepEqual(edits.map((row) => row.text), ["Edit src/a.ts (edits outside a phase's paths)", "Edit src/b.ts (edits outside a phase's paths)"],
    "different paths stay separate rows");
  assert.equal(allowedByDefaultCountText(events), "4 tool calls allowed by default");
  assert.equal(allowedByDefaultCountText([events[1]]), "1 tool call allowed by default");
  assert.equal(allowedByDefaultCountText(Array.from({ length: 200 }, () => events[1])), "200+ tool calls allowed by default");
  assert.equal(allowedByDefaultCountText([events[0]]), "");
});

test("run history: a tool_denied event is a refusal row with the rule's message and its remedy", () => {
  const remedy = { setting: "device_runs.tool_defaults.web_tools", value: "all" };
  const [row] = runHistory([event("d", "tool_denied", { tool: "WebSearch", reason: "outside_phase_tools", setting: remedy.setting,
    remedy, message: "Phase 'Implement' does not research on the web in this Workspace.", session_id: "s" })], []);
  assert.equal(row.title, "Refused: WebSearch");
  assert.equal(row.text, "Phase 'Implement' does not research on the web in this Workspace.");
  assert.equal(row.remedy.key, "web_tools");
  const [plain] = runHistory([event("e", "tool_denied", { tool: "Bash", reason: "destructive_pattern", remedy: null })], []);
  assert.equal(plain.text, "destructive pattern");
  assert.equal(plain.remedy, undefined, "a hard rule has no one-click fix");
});

test("device job: a live tool_denied event marks the running card of its tool with the remedy", () => {
  const jobs = readJobs({ items: [{ id: "j1", status: "running", turn_id: "t1", events: [
    { seq: 1, type: "job_event", body: { turn_id: "t1", kind: "tool_use", tool: "WebSearch", tool_use_id: "u1" } }] }] });
  const remedy = { setting: "device_runs.tool_defaults.web_tools", value: "all" };
  const next = applyJobEvent(jobs, { eventType: "tool_denied", job_id: "j1", turn_id: "t1", tool: "WebSearch",
    message: "This Workspace does not use the web in its runs.", remedy });
  const [card] = turnView(next[0]).items;
  assert.equal(card.status, "error");
  assert.equal(card.output, "This Workspace does not use the web in its runs.");
  assert.equal(card.remedy.key, "web_tools");
  assert.equal(applyJobEvent(jobs, { eventType: "tool_denied", job_id: "other", tool: "WebSearch" }), jobs, "another job: unchanged");
});

test("seat state: the _set flags decide unset vs. stored; an answer without them falls back to in_effect", () => {
  assert.equal(seatStateView("forbidden", true, false).value, "Allowed by default (public/internal data)");
  assert.deepEqual(seatStateView("forbidden", false, false), { mode: "forbidden", value: "Not allowed by default", byDefault: true });
  assert.equal(seatStateView("forbidden", false, true).value, "Not allowed", "explicitly forbidden");
  assert.equal(seatStateView("allowed", true, true).byDefault, false);
});

test("seat state: an unset switch open by default reads 'Allowed by default', not forbidden", () => {
  assert.deepEqual(seatStateView("forbidden", true), { mode: "allowed", value: "Allowed by default (public/internal data)", byDefault: true });
  assert.equal(seatStateView("forbidden", false).value, "Not allowed");
  assert.equal(seatStateView("forbidden", null).mode, "forbidden", "an answer without in_effect keeps the stored switch");
  assert.equal(seatStateView("allowed", false).mode, "allowed", "a stored allow blocked by the classification stays allowed");
  assert.deepEqual(seatRules({ seat_mode: "forbidden", in_effect: true, codex_seat_mode: "forbidden", codex_in_effect: false })
    .map((rule) => rule.value), ["Allowed by default", "Forbidden"]);
});
