// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/policyIdLabels.test.mjs
//
// Readable labels for determining policy ids (policy UX): Workspace names instead of UUIDs, rule names,
// "Platform: …", a custom policy's @name; unknown ids stay readable without the names loaded.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { decisionSentence } from "../../src/admin/components/policyEngine/policyEngineDecisions.ts";
import { policyIdLabel, workspaceLabel } from "../../src/admin/components/policyEngine/policyIdLabels.ts";
import { act, byTestId, load, text } from "./policyEngineHarness.mjs";

const WS = "ade09ac0-5b1e-4f7a-9d0c-1e2f3a4b5c6d";
const NAMES = { workspaces: { [WS]: "Payments" }, policies: { "no-restart": "No rollout restarts" } };

test("platform and classification ids read as words", () => {
  assert.equal(policyIdLabel("platform:client-tool-permit", NAMES), "Platform: client tool permit");
  assert.equal(policyIdLabel("classification:restricted:model-aliases"), "Classification (restricted): model aliases");
  assert.equal(policyIdLabel("classification:confidential:connector:jira:none"), "Classification (confidential): jira connector blocked");
  assert.equal(policyIdLabel("classification:internal:connector:aws:read-only"), "Classification (internal): aws connector read only");
});

test("Workspace ids show the Workspace's name and the rule", () => {
  assert.equal(policyIdLabel(`workspace:${WS}:tool-rule:kubectl-requires-context`, NAMES), "Payments · Workspace rule: kubectl requires context");
  assert.equal(policyIdLabel(`workspace:${WS}:client-deny:2`, NAMES), "Payments · Claude Code deny rule 2");
  assert.equal(policyIdLabel(`workspace:${WS}:command-unparseable`, NAMES), "Payments · Workspace rule: commands that could not be parsed");
  assert.equal(policyIdLabel(`workspace:${WS}:model-denied`, NAMES), "Payments · Model policy: denied models");
  assert.equal(policyIdLabel(`workspace:${WS}:model-allow-all`, NAMES), "Payments · Model policy: all admitted models");
  assert.equal(policyIdLabel(`workspace:${WS}:something-new`, NAMES), "Payments · something new");
  assert.equal(policyIdLabel(`workspace:${WS}:tool-rule:x`), "Workspace ade09ac0… · Workspace rule: x", "unknown Workspace: a short id, never the full UUID");
  assert.equal(workspaceLabel("ws-1", NAMES), "Workspace ws-1");
});

test("custom policies show their @name; unknown ids stay as they are", () => {
  assert.equal(policyIdLabel("no-restart", NAMES), "No rollout restarts");
  assert.equal(policyIdLabel("brand-new"), "brand-new");
  assert.equal(policyIdLabel("platform:", NAMES), "platform:");
});

test("the decision sentence uses the labels when given", () => {
  const record = { decision: "deny", determining: ["no-restart", "platform:tool-permit"], errors: [], legacyDecision: "", legacyReason: "" };
  assert.equal(decisionSentence(record, (id) => policyIdLabel(id, NAMES)), "Cedar: deny by No rollout restarts, Platform: tool permit.");
  assert.equal(decisionSentence(record), "Cedar: deny by no-restart, platform:tool-permit.");
});

test("a policy reference shows the label, keeps the raw id on hover, and copies the raw id", async () => {
  let selected = "";
  const { PolicyRef } = load("admin/components/policyEngine/PolicyRef.tsx", { window: { getSelection: () => ({ toString: () => selected }) } });
  const id = "platform:client-tool-permit";
  let view;
  await act(async () => { view = TestRenderer.create(createElement(PolicyRef, { id })); });
  const ref = byTestId(view, "policy-ref")[0];
  assert.equal(text(ref), "Platform: client tool permit");
  assert.equal(ref.props.title, id);
  const copy = () => {
    const event = { copied: null, prevented: false, clipboardData: { setData: (_type, value) => { event.copied = value; } }, preventDefault: () => { event.prevented = true; } };
    ref.props.onCopy(event);
    return event;
  };
  selected = "Platform: client tool permit";
  assert.deepEqual([copy().copied, copy().prevented], [id, true], "copying the label copies the raw id");
  selected = "denied by Platform: client tool permit and more";
  assert.deepEqual([copy().copied, copy().prevented], [null, false], "a wider selection copies as selected");
});
