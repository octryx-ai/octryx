// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/intakeSyncMode.test.mjs
//
// The Sync of one intake source (backend): the select's choices with the workflow's mode in words, the body
// (null follows the workflow; a draft without the key sends none, so the server keeps the stored mode), the overview
// card's mode in force, and the 422 at the field. Names and values are invented.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  FOLLOW_WORKFLOW,
  cardSyncLabel,
  syncChoices,
  syncModeOfSelect,
  syncSelectValue,
  workflowModeOf,
} from "../../src/chat/work/intake/intakeSyncModel.ts";
import { draftPayload, newDraft } from "../../src/chat/work/intake/workIntakeDraft.ts";
import { refusalOf, stepOfField } from "../../src/chat/work/intake/restIntakeRefusals.ts";
import { restFormOf } from "../../src/chat/work/intake/restIntakeForm.ts";

test("the choices name the workflow's mode now; follow maps to null and back", () => {
  assert.deepEqual(syncChoices("dry_run_only").map((choice) => choice.value), [FOLLOW_WORKFLOW, "dry_run_only", "execute"]);
  assert.equal(syncChoices("dry_run_only")[0].label, "Follow the Workspace workflow (now: dry run only)");
  assert.equal(syncChoices("execute")[0].label, "Follow the Workspace workflow (now: execute)");
  assert.equal(syncChoices(null)[0].label, "Follow the Workspace workflow (now: no mode set, nothing is written)");
  assert.equal(syncChoices(undefined)[0].label, "Follow the Workspace workflow (now: reading…)");
  assert.equal(syncModeOfSelect(FOLLOW_WORKFLOW), null);
  assert.equal(syncModeOfSelect("execute"), "execute");
  assert.equal(syncSelectValue(null), FOLLOW_WORKFLOW);
  assert.equal(syncSelectValue(undefined), FOLLOW_WORKFLOW);
  assert.equal(syncSelectValue("bogus"), FOLLOW_WORKFLOW, "an unknown stored value reads as following, like the server");
});

test("the body: a set mode and null are sent; a draft without the key sends none (the server keeps the mode)", () => {
  for (const kind of ["jira", "servicenow", "custom_rest"]) {
    const fresh = newDraft(kind, "conn");
    const rest = kind === "custom_rest" ? { rest: { ...restFormOf({}, {}), operation: "list_tickets" } } : {};
    assert.equal("sync_mode" in draftPayload({ ...fresh, ...rest }).how, false, `${kind}: untouched new draft`);
    assert.equal(draftPayload({ ...fresh, ...rest, how: { ...fresh.how, sync_mode: "dry_run_only" } }).how.sync_mode, "dry_run_only", kind);
    const back = draftPayload({ ...fresh, ...rest, how: { ...fresh.how, sync_mode: null } }).how;
    assert.equal("sync_mode" in back && back.sync_mode === null, true, `${kind}: null follows the workflow`);
  }
});

test("the overview card: the mode in force, marked when the source sets one that differs; the workflow's mode", () => {
  assert.deepEqual(cardSyncLabel({ sync_mode: null, effective_sync_mode: "dry_run_only", workflow_sync_mode: "dry_run_only" }),
    { text: "Dry run only", own: false });
  assert.deepEqual(cardSyncLabel({ sync_mode: "execute", effective_sync_mode: "execute", workflow_sync_mode: null }),
    { text: "Execute", own: true });
  assert.deepEqual(cardSyncLabel({ sync_mode: null, effective_sync_mode: null, workflow_sync_mode: null }),
    { text: "No mode set, nothing is written", own: false });
  assert.equal(workflowModeOf([{ workflow_sync_mode: null }]), null);
  // Every intake names the workflow's mode itself; an own value equal to it is not "set for this source".
  assert.equal(workflowModeOf([{ sync_mode: "execute", effective_sync_mode: "execute", workflow_sync_mode: "dry_run_only" }]), "dry_run_only");
  assert.deepEqual(cardSyncLabel({ sync_mode: "dry_run_only", effective_sync_mode: "dry_run_only", workflow_sync_mode: "dry_run_only" }),
    { text: "Dry run only", own: false });
  assert.deepEqual(cardSyncLabel({ sync_mode: "execute", effective_sync_mode: "execute", workflow_sync_mode: "dry_run_only" }),
    { text: "Execute", own: true });
  assert.equal(workflowModeOf([]), undefined, "no intake yet: the caller reads the workflows");
});

test("a refused Sync (422) is shown in words at the select, on the How step", () => {
  const refusal = refusalOf({ status: 422, code: null, message: "how.sync_mode must be one of: dry_run_only, execute",
    detail: { state: "invalid_request", field: "how.sync_mode" } });
  assert.equal(refusal.field, "how.sync_mode");
  assert.match(refusal.text, /Pick one of the Sync choices/);
  assert.equal(stepOfField(refusal.field), 3);
});
