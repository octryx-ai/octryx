// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workItemPlainLanguage.test.mjs
// The Work item side panel speaks plain language: no codes (human_only, missing_acceptance_criteria,
// missing_repository_evidence, sync_config), no Jira "goal: <null>" and no internal field names of the source mapping.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";

import {
  automationModeText, automationPolicySourceText, automationReasonText, automationReasonsText,
} from "../../src/chat/work/workAutomationText.ts";
import { sprintGoal } from "../../src/chat/work/workItemDetailModel.ts";

const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");

test("automation mode, reasons and policy source read as words", () => {
  assert.equal(automationModeText("human_only"), "Humans only");
  assert.equal(automationModeText("needs_review"), "Suggest only");
  assert.equal(automationModeText("some_new_mode"), "Some new mode", "an unknown code is shown in words");
  assert.deepEqual(automationReasonsText(["missing_acceptance_criteria", "missing_repository_evidence"]),
    ["No acceptance criteria", "No repository named"]);
  assert.equal(automationReasonText("excluded_label:no-octryx"), 'Excluded by the label "no-octryx"');
  assert.equal(automationReasonText("work_state:done"), "Already done");
  assert.deepEqual(automationReasonsText(undefined), []);
  assert.equal(automationPolicySourceText("sync_config"), "Intake settings");
  assert.equal(automationPolicySourceText("default"), "Default rules");
});

test("Jira's <null> sprint goal is no goal", () => {
  assert.equal(sprintGoal({ name: "S 33.1", goal: "<null>" }), "");
  assert.equal(sprintGoal({ name: "S 33.1", goal: "null" }), "");
  assert.equal(sprintGoal({ name: "S 33.1", goal: "Ship the release" }), "Ship the release");
});

test("the panel uses the words, and folds the internal field names away", () => {
  const parts = fs.readFileSync(path.join(SRC, "chat/work/WorkItemDetailParts.tsx"), "utf8");
  assert.match(parts, /value=\{automationModeText\(eligibility\.mode\)\}/);
  assert.match(parts, /value=\{automationReasonsText\(eligibility\.review_reasons\)\}/);
  assert.match(parts, /value=\{automationPolicySourceText\(eligibility\.policy_source\)\}/);
  const panel = fs.readFileSync(path.join(SRC, "chat/work/WorkItemDetailPanel.tsx"), "utf8");
  const section = panel.slice(panel.indexOf('<DetailSection title="Source Mapping">'));
  const details = section.indexOf("<details");
  assert.ok(details > 0 && details < section.indexOf("<MappingGrid"), "the field ownership is inside the disclosure");
});

// Current product states retain the same semantic colors as the generic states.
test("current product state badges preserve their semantic tones", async () => {
  const { badgeTone } = await import("../../src/chat/work/workUtils.ts");
  assert.equal(badgeTone("Octryx Direct"), "active");
  assert.equal(badgeTone("Octryx Requested"), "running");
  assert.equal(badgeTone("Octryx Blocked"), "attention");
  assert.equal(badgeTone("Octryx Review"), "attention");
  assert.equal(badgeTone("done"), "active");
  assert.equal(badgeTone("unknown status"), "neutral");
});
