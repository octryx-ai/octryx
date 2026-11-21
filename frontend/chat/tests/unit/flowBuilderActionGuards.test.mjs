// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/flowBuilderActionGuards.test.mjs
//
// Behaviour guards for the Flow Builder's test case and publish actions, whose long functions are split into smaller
// parts: every path (refused, invalid input, success, failure) records the same requests and state updates.
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { test } from "node:test";
import { loadModule } from "./adminDigestRenderHarness.mjs";

// Records every setter call as "name=value" and every request as "METHOD url body".
function recorder(answers = {}) {
  const log = [];
  const setter = (name) => (value) => log.push(`${name}=${JSON.stringify(value)}`);
  const readJson = async (url, init = {}) => {
    log.push(`${init.method || "GET"} ${url}${init.body ? ` ${init.body}` : ""}`);
    const answer = Object.entries(answers).find(([suffix]) => url.endsWith(suffix))?.[1];
    if (answer instanceof Error) throw answer;
    return answer ?? {};
  };
  return { log, setter, readJson };
}

const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");
const TRACE = { run: { id: "run-1" }, node_runs: [{ id: "nr-1" }] };

function testCaseInput(rec, overrides = {}) {
  const names = ["setError", "setTestBusy", "setTestCases", "setRunTrace", "setSelectedTraceNodeRunId", "setOperationsOpen"];
  return {
    readJson: rec.readJson, selectedFlow: { id: "f-1", project_id: "p-flow" }, authoring: { testsAvailable: true }, runWorkspaceId: "p-flow",
    traceInputJson: '{"request":"x"}', loadRunQuality: async (runId) => rec.log.push(`quality ${runId}`),
    ...Object.fromEntries(names.map((name) => [name, rec.setter(name)])), ...overrides,
  };
}

test("flow test cases: load, create, run one and run all on every path", async () => {
  const { flowTestCaseActions } = loadModule("admin/components/flowBuilder/flowTestCaseActions.ts");
  const logs = [];
  const run = async (answers, overrides, action) => {
    const rec = recorder(answers);
    const silent = console.error;
    console.error = () => {};
    try { await action(flowTestCaseActions(testCaseInput(rec, overrides))); } finally { console.error = silent; }
    logs.push(rec.log.join(" | "));
  };
  const items = { "/test-cases": { items: [{ id: "tc-1" }] } };
  await run(items, {}, (a) => a.loadTestCases());
  await run(items, {}, (a) => a.loadTestCases("f-2"));
  await run({ "/test-cases": { items: "bad" } }, {}, (a) => a.loadTestCases());
  await run({ "/test-cases": new Error("down") }, {}, (a) => a.loadTestCases());
  await run(items, { selectedFlow: null }, (a) => a.loadTestCases());
  await run(items, {}, (a) => a.createTestCase("Case", '{"answer":"y"}'));
  await run(items, { runWorkspaceId: "p-1" }, (a) => a.createTestCase("Case", ""));
  await run(items, { runWorkspaceId: null }, (a) => a.createTestCase("Case", "")); // no Workspace: nothing is sent
  await run(items, {}, (a) => a.createTestCase("Case", "not json"));
  await run(items, { traceInputJson: "[1]" }, (a) => a.createTestCase("Case", "{}"));
  await run({ "/test-cases": new Error("refused") }, {}, (a) => a.createTestCase("Case", "{}"));
  await run(items, { selectedFlow: null }, (a) => a.createTestCase("Case", "{}"));
  await run(items, { authoring: { testsAvailable: false } }, (a) => a.createTestCase("Case", "{}"));
  await run({ ...items, "/run": { trace: TRACE } }, {}, (a) => a.runTestCase("tc-1"));
  await run({ ...items, "/run": { trace: { run: { id: "run-2" } } } }, {}, (a) => a.runTestCase("tc-1"));
  await run({ ...items, "/run": {} }, {}, (a) => a.runTestCase("tc-1"));
  await run({ "/run": new Error("boom") }, {}, (a) => a.runTestCase("tc-1"));
  await run({ "/run": "x" }, { selectedFlow: null }, (a) => a.runTestCase("tc-1"));
  await run({}, { authoring: { testsAvailable: false } }, (a) => a.runTestCase("tc-1"));
  await run(items, {}, (a) => a.batchRunTestCases());
  await run({ "/batch-run": new Error("busy") }, {}, (a) => a.batchRunTestCases());
  await run({}, { selectedFlow: null }, (a) => a.batchRunTestCases());
  await run({}, { authoring: { testsAvailable: false } }, (a) => a.batchRunTestCases());
  assert.equal(logs.length, 23);
  assert.match(logs[5], /POST \/api\/v1\/flows\/f-1\/test-cases .*"project_id":"p-flow"/);
  assert.match(logs[6], /POST \/api\/v1\/flows\/f-1\/test-cases .*"project_id":"p-1"/);
  assert.equal(logs[7], 'setError="Choose the Workspace this run starts in."');
  assert.equal(sha(logs), "e0f0e903283945b6c8e5b181effeca499fa33bfd0d4b6eeb4c2fd9639b9befa4");
});

function publishInput(rec, overrides = {}) {
  const names = ["setError", "setBusy", "setSelectedFlow", "setValidationReport", "setRunTrace", "setSelectedTraceNodeRunId",
    "setQualitySummary", "setPublishGateOpen"];
  return {
    readJson: rec.readJson, loadFlowCapabilities: async () => rec.log.push("capabilities"),
    authoring: { publishable: true, version: { id: "v-2" } }, description: " Answers questions ", name: "Flow",
    activeDefinition: { evidence_contract: { minimum: 1 } }, selectedCapability: null,
    selectedFlow: { id: "f-1", current_version_id: "v-1" },
    ...Object.fromEntries(names.map((name) => [name, rec.setter(name)])), ...overrides,
  };
}

test("flow publish: publish, unpublish and reject on every path", async () => {
  const { flowBuilderPublishActions } = loadModule("admin/components/flowBuilder/flowBuilderPublishActions.ts");
  const logs = [];
  const run = async (answers, overrides, action) => {
    const rec = recorder(answers);
    await action(flowBuilderPublishActions(publishInput(rec, overrides)));
    logs.push(rec.log.join(" | "));
  };
  const row = { id: "f-1", versions: [{ id: "v-1", validation_report: { valid: false } }, { id: "v-2", validation_report: { valid: true } }] };
  const answers = { "/publish": row, "/unpublish": row, "/archive": row };
  await run(answers, {}, (a) => a.publishSelectedFlow());
  await run({ "/publish": { id: "f-1" } }, { description: "  ", activeDefinition: {} }, (a) => a.publishSelectedFlow());
  await run({ "/publish": new Error("gate closed") }, {}, (a) => a.publishSelectedFlow());
  await run({ "/publish": "x" }, { authoring: { publishable: true, version: null } }, (a) => a.publishSelectedFlow());
  await run({}, { authoring: { publishable: false } }, (a) => a.publishSelectedFlow());
  await run(answers, {}, (a) => a.unpublishSelectedCapability());
  await run({ "/unpublish": { id: "f-1" } }, { selectedCapability: { version_id: "v-9" } }, (a) => a.unpublishSelectedCapability());
  await run({ "/unpublish": new Error("no") }, {}, (a) => a.unpublishSelectedCapability());
  await run({}, { selectedFlow: null }, (a) => a.unpublishSelectedCapability());
  await run(answers, {}, (a) => a.rejectSelectedFlow());
  await run({ "/archive": {} }, {}, (a) => a.rejectSelectedFlow());
  await run({ "/archive": new Error("locked") }, {}, (a) => a.rejectSelectedFlow());
  await run({}, { selectedFlow: null }, (a) => a.rejectSelectedFlow());
  assert.equal(logs.length, 13);
  assert.match(logs[0], /"purpose":"Answers questions"/);
  assert.equal(sha(logs), "ffa5dfbb1a467c0b87063063eb4550b1e3d9783c5f27424dc9be9e8af7791546");
});
