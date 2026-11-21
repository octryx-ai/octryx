import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";
import { payloadView } from "../../src/chat/workflowRun/workflowRunPayloadView.ts";

const loader = registerHooks({ load(url, context, nextLoad) {
  if (url.endsWith(".tsx")) return { format: "module", shortCircuit: true,
    source: transpileModule(readFileSync(new URL(url), "utf8"), {
      compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
    }).outputText };
  return nextLoad(url, context);
} });
const { RunPayload } = await import("../../src/chat/workflowRun/RunPayload.tsx");
loader.deregister();
const hash = `sha256:${"a".repeat(64)}`;
const record = kind => ({ schema_version: `${kind}/v1`, version: 3, hash });
const waiting = (kind, output, rest = {}) => ({ kind: "awaiting_confirmation", subject: "advance",
  payload: { shows: kind, output, ...rest }, payload_hash: `sha256:${"b".repeat(64)}` });

test("specification cards retain the actual signed test-alert marker", () => {
  assert.match(payloadView(waiting("idea_frame", record("idea_frame"), { test_alert: true })).testAlert, /test alert/i);
  assert.equal(payloadView(waiting("idea_frame", record("idea_frame"))).testAlert, null);
});

for (const kind of ["idea_frame", "research_plan", "research_brief", "spec"]) {
  test(`${kind}: complete nested scope, budget, criteria and sources are inspectable`, () => {
    const output = { ...record(kind), summary: "A bounded proposal", scope: { in_scope: ["Read only"], out_of_scope: [] },
      idea_frame_ref: { kind: "idea_frame", version: 1, hash, decision_id: "human-decision" },
      budget: { tokens: 100000, cost_usd: 1, active_seconds: 1200, tool_calls: 40 },
      documentation_audience: { semantics: "workspace_readers", description: "The current workspace's readers" },
      criteria: [{ id: "AC1", story_ids: ["ST1"], given: "An admitted source", when: "A reader opens it",
        then: "The evidence is inspectable" }],
      evidence: [{ evidence_key: "exact-source-key", call_id: "persisted-call-id", text: "Observed source facts",
        source_acl: { workspace_id: "current-workspace", principal_user_id: "actual-reader", acl_hash: hash } }],
      open_questions: [], uncertainty: [] };
    const view = payloadView(waiting(kind, output));
    assert.deepEqual(JSON.parse(view.text), output);
    for (const field of ["scope", "budget", "documentation_audience", "source_acl"]) {
      assert.ok(view.text.includes(`"${field}": {\n`));
    }
    assert.match(view.text, /The evidence is inspectable/);
    assert.ok(view.lines.includes("Record version 3"));
    assert.ok(view.lines.includes(`Record hash ${hash}`));
    if (kind === "research_plan") {
      assert.match(view.lines.join(" "), /after each completed phase turn/);
      assert.match(view.lines.join(" "), /can overshoot/);
      assert.match(view.lines.join(" "), /not hard per-read caps/);
    }
  });
}

test("withheld cards show only missing reason; old text, context or output cannot reconstruct sources", () => {
  for (const kind of ["idea_frame", "research_plan", "research_brief", "spec"]) {
    const view = payloadView(waiting(kind, null, { missing: "The current source is withheld.",
      text: "OLD PRIVATE SOURCE", context: { output: { text: "OLD PRIVATE SOURCE" } } }));
    assert.equal(view.text, null);
    assert.deepEqual(view.lines, []);
    assert.equal(view.missing, "The current source is withheld.");
    assert.doesNotMatch(JSON.stringify(view), /OLD PRIVATE SOURCE/);
    assert.equal(payloadView(waiting(kind, { ...record(kind), text: "OLD PRIVATE SOURCE" },
      { missing: "The current source is withheld." })).text, null);
  }
});

test("last criterion and final source remain present beyond common preview limits", () => {
  const output = { ...record("spec"),
    criteria: Array.from({ length: 20 }, (_, i) => ({ id: `AC${i + 1}`, then: `Criterion ${i + 1}` })),
    evidence: Array.from({ length: 4 }, (_, i) => ({ evidence_key: `key-${i}`, text: "e".repeat(7000) + ` END${i}` })) };
  const view = payloadView(waiting("spec", output));
  assert.ok(view.text.length > 28000);
  assert.match(view.text, /Criterion 20/);
  assert.match(view.text, / END3/);
  assert.deepEqual(JSON.parse(view.text), output);
});

test("the shared pre renders untrusted markup as escaped text", () => {
  const view = payloadView(waiting("spec", { ...record("spec"), summary: "<script>window.untrusted=true</script>" }));
  const html = renderToStaticMarkup(createElement(RunPayload, { view }));
  assert.match(html, /<pre class="workflow-run-banner__text">/);
  assert.match(html, /&lt;script&gt;/);
  assert.doesNotMatch(html, /<script>/);
});

test("malformed records do not produce a source-bearing confirmation projection", () => {
  for (const output of [null, [], "old prose", { ...record("spec"), version: 0 },
    { ...record("spec"), hash: "sha256:short" }, { ...record("spec"), schema_version: "idea_frame/v1" }]) {
    const view = payloadView(waiting("spec", output));
    assert.equal(view.text, null);
    assert.ok(view.missing);
  }
});

test("other workflow kinds retain the existing generic card", () => {
  const view = payloadView(waiting("definition_of_ready", { summary: "Existing triage behavior", complete: true }));
  assert.ok(view.lines.includes("summary: Existing triage behavior"));
  assert.ok(view.lines.includes("complete: yes"));
  assert.equal(view.text, null);
});
