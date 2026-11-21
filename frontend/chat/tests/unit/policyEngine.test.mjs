// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/policyEngine.test.mjs
//
// Cedar policy engine admin pages: Settings → Governance → Policies
// (status, guarded enforce switch, custom policy draft → validate → save → submit → approve → publish, diff,
// rollback), Policy test bench (questions from real entities, saved cases), Policy decisions (filters, "why was this
// blocked"). Live validation uses the real cedar-wasm Node build against the backend's schema file. Requests are stubs.

import assert from "node:assert/strict";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { benchRequest, readBenchResult, readEntities, resourceField, testCaseLabel, readTestCases } from "../../src/admin/components/policyEngine/policyEngineBench.ts";
import { decisionHref, decisionSentence, readDecisions, readUrlDecision } from "../../src/admin/components/policyEngine/policyEngineDecisions.ts";
import { diffSummary, readTestReport, readVersions, refusalText } from "../../src/admin/components/policyEngine/policyEngineVersions.ts";
import { enforceBlockers, outcomeTotals, readStatus, readinessLine } from "../../src/admin/components/policyEngine/policyEngineStatus.ts";
import { suggestionsFor, vocabularyOf } from "../../src/admin/components/policyEngine/cedarLanguage.ts";
import { issuesOf } from "../../src/admin/components/policyEngine/cedarValidation.ts";
import { SCHEMA, STATUS, act, byTestId, click, load, server, text, tick } from "./policyEngineHarness.mjs";

const require = createRequire(import.meta.url);
const HERE = path.dirname(fileURLToPath(import.meta.url));
const FORBID = '@id("no-restart")\nforbid (principal in Role::"sre", action == Action::"run_command", resource)\nwhen { resource.prefixes.contains("kubectl rollout restart") };\n';

// ---- model -----------------------------------------------------------------------------------------------------

test("status: counters, totals, enforce blockers in words; unknown mode falls back to shadow", () => {
  const status = readStatus(STATUS());
  assert.equal(status.mode, "shadow");
  assert.deepEqual(outcomeTotals(status.counters), { match: 14, mismatch: 1, custom_policy: 2, error: 0 });
  assert.deepEqual(enforceBlockers(status), [
    "The shadow period is not over yet.", "Cedar disagreed with the existing checks during the shadow period.",
  ]);
  assert.equal(readStatus({ ...STATUS(), mode: "loud" }).mode, "shadow");
  assert.equal(readStatus(null), null);
  assert.equal(readStatus({ ...STATUS(), custom: { valid: false } }).customValid, false);
  // Judge fixes (Delivery 3): an unparseable published set falls back to shadow and its decisions are counted;
  // dropped decision-log records block enforcement.
  const invalid = readStatus({ ...STATUS(), custom: { valid: false, fallback: "shadow" }, custom_fallbacks: { seat: 2, gateway_tool_check: 3 } });
  assert.equal(invalid.customFallbacks, 5);
  assert.equal(readStatus(STATUS()).customFallbacks, 0);
  const dropped = readStatus({ ...STATUS(), enforce: { ...STATUS().enforce, reasons: ["decision_log_records_dropped"] } });
  assert.match(enforceBlockers(dropped)[0], /dropped/);
  // The header card's readiness line (policy UX).
  assert.equal(readinessLine(status, new Date("2026-10-07T04:00:00Z")), "Enforce not ready");
  const waiting = readStatus(STATUS({ enforce: { ...STATUS().enforce, mismatches: 0, reasons: ["window_not_elapsed"] } }));
  assert.equal(readinessLine(waiting, new Date("2026-10-07T04:00:00Z")), "Enforce ready in 6 h");
  assert.equal(readinessLine(readStatus(STATUS({ enforce: { ...STATUS().enforce, ready: true, reasons: [] } }))), "Enforce ready");
  assert.equal(readinessLine(readStatus(STATUS({ mode: "enforce" }))), "Enforcing");
});

test("versions, test reports, diff summary and refusal texts", () => {
  const versions = readVersions({ items: [
    { version: 3, state: "draft", policy_ids: ["a"], test_report: { results: [{ id: "t", name: "n", expected: "deny", actual: "allow", passed: false }] } },
    { version: 2, state: "published", policy_ids: [] }, { state: "x" },
  ] });
  assert.deepEqual(versions.map((item) => item.version), [3, 2]);
  assert.equal(versions[0].testReport.ok, false);
  assert.equal(readTestReport({ results: [] }).ok, true);
  assert.deepEqual(diffSummary("x\ny\nz", "x\nz\nw\nw"), { added: 2, removed: 1 });
  assert.match(refusalText({ status: 409, code: "policy_set_self_approval" }), /Four-eyes/);
  assert.match(refusalText({ status: 409, code: "policy_set_tests_failed" }), /blocked/);
  assert.match(refusalText({ status: 409, code: "policy_set_retire_requires_review" }), /review/);
  assert.equal(refusalText({ status: 403 }), "Platform admin role required.");
  assert.equal(refusalText(new Error("boom")), "Refused: boom.");
});

test("bench request per action, entity pickers and saved-case labels", () => {
  assert.equal(resourceField("run_command"), "command");
  assert.equal(resourceField("write_connector"), "tool");
  assert.equal(resourceField("use_seat"), "none");
  const base = { workspaceId: "ws", userId: "u", action: "run_command", value: "kubectl get", tool: "", params: "" };
  assert.deepEqual(benchRequest(base).request, { workspace_id: "ws", user_id: "u", action: "run_command", resource: { command: "kubectl get" } });
  assert.equal(benchRequest({ ...base, workspaceId: "" }).problem, "Pick a Workspace.");
  assert.equal(benchRequest({ ...base, action: "call_tool", tool: "run_kubectl", params: "[1]" }).problem, "Tool arguments must be a JSON object.");
  assert.deepEqual(benchRequest({ ...base, action: "call_tool", tool: "run_kubectl", params: '{"args":"get"}' }).request.resource,
    { tool: "run_kubectl", params: { args: "get" } });
  assert.deepEqual(benchRequest({ ...base, action: "write_path", value: " .env " }).request.resource, { path: ".env", tool: "Edit" });
  assert.deepEqual(benchRequest({ ...base, action: "call_model", value: "" }).request.resource, { alias: "" });
  assert.equal(benchRequest({ ...base, action: "use_seat" }).request.user_id, "u");
  const entities = readEntities({ workspaces: [{ id: "w", name: "Acme Orders", classification: "internal" }], users: [{ id: "u", username: "alex" }], tools: ["run_kubectl", 3], actions: ["use_seat"] });
  assert.deepEqual(entities.users, [{ id: "u", name: "alex" }]);
  assert.deepEqual(entities.tools, ["run_kubectl"]);
  const [saved] = readTestCases({ items: [{ id: "c", name: "restart", expected: "deny", request: { action: "run_command", resource: { command: "kubectl rollout restart" } } }] });
  assert.equal(testCaseLabel(saved), "run_command: kubectl rollout restart → expect deny");
});

test("decision log records, the sentence and the 'why was this blocked' link", () => {
  const { items, total } = readDecisions({ total: 1, items: [{ id: "d-1", point: "gateway_tool_check", outcome: "custom_policy", actor: { principal: "AgentSession::s" },
    action: "run_command", resource: "Bash: kubectl rollout restart", decision: "deny", determining_policies: ["no-restart"], errors: [],
    legacy: { decision: "allow", reason: "no_rule_matched" }, policy_set: { custom_version: 2 }, latency_ms: 0.3 }, { nope: 1 }] });
  assert.equal(total, 1);
  assert.equal(items.length, 1);
  assert.equal(decisionSentence(items[0]), "Cedar: deny by no-restart; the existing check said allow (no_rule_matched).");
  assert.equal(decisionHref("d-1"), "/chat?area=operations&tab=observabilityDecisions&decision=d-1");
  assert.equal(readUrlDecision("?decision=d-1"), "d-1");
  assert.equal(readUrlDecision("?decision=<script>"), null);
  assert.equal(readBenchResult({ nope: true }), null);
  assert.deepEqual(readBenchResult({ decision: "allow", notes: ["n", 3] }).notes, ["n"]);
});

// ---- Cedar language and live validation --------------------------------------------------------------------------

const cedarWasm = require(path.resolve(HERE, "../../node_modules/@cedar-policy/cedar-wasm/nodejs/cedar_wasm.js"));

test("completion comes from the server schema: actions, context fields, attributes", () => {
  const vocabulary = vocabularyOf(cedarWasm.schemaToJson(SCHEMA).json);
  assert.ok(vocabulary.actions.includes("run_command") && vocabulary.entityTypes.includes("Workspace"));
  assert.deepEqual(vocabulary.contextFields, ["admission_verified", "connections", "content", "folder_allowlisted", "origin", "point", "profile", "reads_logs", "route", "tool", "workspace", "writes"]);
  assert.ok(suggestionsFor('action == Action::"', vocabulary).some((item) => item.insertText === "run_command"));
  assert.ok(suggestionsFor("action == Action::", vocabulary).some((item) => item.insertText === '"run_command"'));
  assert.ok(suggestionsFor("when { resource.", vocabulary).some((item) => item.label === "prefixes" && item.detail === "Command"));
  assert.ok(suggestionsFor("when { context.", vocabulary).some((item) => item.label === "reads_logs"));
  assert.ok(suggestionsFor("", vocabulary).some((item) => item.label === "forbid…"));
});

test("live validation with the real wasm build: schema and parse errors with their positions", () => {
  assert.deepEqual(issuesOf(cedarWasm, SCHEMA, FORBID), []);
  const typo = FORBID.replace("resource.prefixes", "resource.prefix");
  const [issue] = issuesOf(cedarWasm, SCHEMA, typo);
  assert.match(issue.message, /prefix/);
  assert.equal(typo.slice(issue.start, issue.end).includes("resource.prefix"), true);
  const [broken] = issuesOf(cedarWasm, SCHEMA, "forbid (principal");
  assert.equal(broken.severity, "error");
});

// ---- rendered ----------------------------------------------------------------------------------------------------

test("rendered test bench: ask with real entities, see the deciding policy and the legacy decision, save a case", async () => {
  const srv = server((call) => {
    if (call.url.endsWith("/entities")) return { status: 200, body: { workspaces: [{ id: "ws", name: "Acme Orders", classification: "internal" }], users: [{ id: "u", username: "sre-1" }], tools: ["run_kubectl"], model_aliases: ["octryx-sonnet"], actions: ["use_seat", "run_command"], data_policy_classes: ["internal"] } };
    if (call.url.endsWith("/tests") && call.method === "GET") return { status: 200, body: { items: [] } };
    if (call.url.endsWith("/test-bench")) return { status: 200, body: { decision: "deny", action: "run_command", principal: "User::u", resource: "Bash: kubectl rollout restart", determining: [{ id: "no-restart", source: "custom", text: FORBID }, { id: "platform:client-tool-permit", source: "platform", text: "" }], errors: [], legacy: { decision: "allow", reason: "no_rule_matched" }, policy_source: "published version 2", notes: ["evaluated as User::unknown"] } };
    if (call.url.endsWith("/tests") && call.method === "POST") return { status: 201, body: { id: "c" } };
    return { status: 404, body: {} };
  });
  const { AdminPolicyTestBench } = load("admin/components/policyEngine/AdminPolicyTestBench.tsx", { fetch: srv.fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminPolicyTestBench)); });
  await tick();
  await act(async () => { byTestId(view, "bench-user")[0].props.onChange({ target: { value: "u" } }); });
  await act(async () => { byTestId(view, "bench-action")[0].props.onChange({ target: { value: "run_command" } }); });
  await act(async () => { byTestId(view, "bench-value")[0].props.onChange({ target: { value: "kubectl rollout restart deploy/x" } }); });
  await click(view, "bench-ask");
  const asked = srv.calls.find((call) => call.url.endsWith("/test-bench"));
  assert.deepEqual(asked.body, { workspace_id: "ws", user_id: "u", action: "run_command", resource: { command: "kubectl rollout restart deploy/x" } });
  assert.match(text(byTestId(view, "bench-decision")[0]), /^Denied/);
  assert.match(text(byTestId(view, "bench-legacy")[0]), /allow \(no_rule_matched\)/);
  assert.match(text(byTestId(view, "bench-determining")[0]), /no-restart Custom policy/);
  assert.match(text(byTestId(view, "bench-determining")[0]), /Platform: client tool permit Platform/, "a readable label and source, not the raw id");
  assert.equal(byTestId(view, "policy-ref")[1].props.title, "platform:client-tool-permit");
  assert.equal(text(byTestId(view, "bench-note")[0]), "evaluated as User::unknown");
  await act(async () => { byTestId(view, "bench-case-name")[0].props.onChange({ target: { value: "restart needs non-prod" } }); });
  await click(view, "bench-save-case");
  const saved = srv.calls.find((call) => call.url.endsWith("/tests") && call.method === "POST");
  assert.deepEqual(saved.body, { name: "restart needs non-prod", expected: "deny", request: asked.body });
});

