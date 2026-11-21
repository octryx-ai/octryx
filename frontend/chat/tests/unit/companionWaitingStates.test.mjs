import assert from "node:assert/strict";
import test from "node:test";

import { PAUSE_REASON, WAITING_SENTENCE, pausedSentence, runStatePhrase, waitingSentence } from "../../src/chat/companion/companionLabels.ts";
import { areaWithWorkspace, publishActiveWorkspaceName, readActiveWorkspaceName } from "../../src/chat/workspace/activeWorkspaceName.ts";
import { workspaceSwitchLabel } from "../../src/chat/workspace/globalWorkspaceModel.ts";

// Every waiting kind and pause reason the backend can send (WAITING_* / PAUSE_* constants).
const BACKEND_WAITING = ["awaiting_subagents", "awaiting_approval", "watching", "awaiting_tool_approval", "sub_workflow",
  "waiting_review", "awaiting_review", "waiting_for_reply", "handoff", "functional_acceptance", "waiting_for_device",
  "awaiting_confirmation", "waiting_children", "audience_receipt", "waiting_approval", "allowed_awaiting_approval"];
const BACKEND_PAUSE = ["acceptance_timeout", "action_failed", "approval_timeout", "audience_unproven", "budget_limit",
  "content_blocked", "documentation_missing", "environment_not_ready", "evidence_unresolved", "loop_limit",
  "needs_configuration", "no_reply", "publish_unverified", "review_no_decision", "runtime_failed", "watch_timeout",
  "workspace_dirty"];

test("Every backend waiting kind reads as a sentence, never the raw value", () => {
  for (const kind of BACKEND_WAITING) {
    assert.ok(WAITING_SENTENCE[kind], `mapped: ${kind}`);
    const phrase = runStatePhrase("waiting", "", kind, "Working");
    assert.match(phrase, /^Waiting/);
    assert.ok(!phrase.includes("_") && phrase !== `Waiting for ${kind.replace(/_/g, " ")}`, `no raw value for ${kind}: ${phrase}`);
  }
  assert.equal(runStatePhrase("waiting", "review", "awaiting_confirmation", "Working"), "Waiting for your confirmation");
  assert.equal(runStatePhrase("waiting", "implement", "watching", "Working"), "Waiting for merge");
  assert.equal(runStatePhrase("waiting", "merged", "", "Working"), "Waiting for merge");
  assert.equal(waitingSentence("awaiting_answer"), "Waiting for your answer");
  assert.equal(waitingSentence("ci"), "Waiting for checks");
  assert.equal(waitingSentence("schedule"), "Waiting for its schedule");
  assert.equal(waitingSentence("device"), "Waiting for the device");
  assert.equal(runStatePhrase("waiting", "x", "something_new", "Working"), "Waiting", "unknown never shows the raw value");
  assert.equal(runStatePhrase("running", "x", "awaiting_confirmation", "Working"), "Working");
  assert.equal(runStatePhrase("waiting", "x", "watching", "Finished"), "Finished", "a finished run keeps its word");
});

test("Every backend pause reason reads as \"Paused: <reason>\"; unknown reads \"Paused\"", () => {
  for (const reason of BACKEND_PAUSE) {
    assert.ok(PAUSE_REASON[reason], `mapped: ${reason}`);
    const phrase = runStatePhrase("paused", "", "", "Needs you", reason);
    assert.match(phrase, /^Paused: [a-z]/);
    assert.ok(!phrase.includes("_"), phrase);
  }
  assert.equal(pausedSentence("budget_limit"), "Paused: the budget limit was reached");
  assert.equal(pausedSentence("mystery_reason"), "Paused");
  assert.equal(runStatePhrase("paused", "", "", "Working"), "Paused");
});

test("The area head writes the active Workspace out; the switch names it in full", () => {
  assert.equal(areaWithWorkspace("Work", "Test"), "Work · Test");
  assert.equal(areaWithWorkspace("Work", ""), "Work");
  publishActiveWorkspaceName("  Acme Orders ");
  assert.equal(readActiveWorkspaceName(), "Acme Orders");
  publishActiveWorkspaceName(null);
  assert.equal(readActiveWorkspaceName(), "");
  assert.equal(workspaceSwitchLabel("ux first run"), "Workspace: ux first run · change");
});
