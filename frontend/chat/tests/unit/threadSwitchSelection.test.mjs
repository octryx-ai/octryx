// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// A composer pick made while a thread switch loads belongs to the thread
// being opened, never to the thread that was still shown.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  beginThreadSwitch,
  chooseDuringSwitch,
  completeThreadSwitch,
  IDLE_THREAD_SWITCH,
} from "../../src/chat/threadSwitchSelection.ts";

test("a pick between 'New chat' and the loaded thread wins and is persisted for the new thread", () => {
  let state = beginThreadSwitch("thread-x", "");
  const pick = chooseDuringSwitch(state, "coding-change-tdd");
  assert.equal(pick.persistForShownThread, false, "never written to the thread still shown");
  state = pick.state;

  const done = completeThreadSwitch(state, "");
  assert.deepEqual(done, { state: IDLE_THREAD_SWITCH, value: "coding-change-tdd", persistPick: true });
});

test("the default entry picked during a switch is a real pick", () => {
  const { state } = chooseDuringSwitch(beginThreadSwitch("thread-x", "thread-y"), "");
  assert.deepEqual(completeThreadSwitch(state, "aws-topology-diagram-routing"), {
    state: IDLE_THREAD_SWITCH,
    value: "",
    persistPick: true,
  });
});

test("without a pick the switch restores the opened thread's own selection", () => {
  const done = completeThreadSwitch(beginThreadSwitch("thread-x", "thread-y"), "knowledge-request-routing");
  assert.deepEqual(done, { state: IDLE_THREAD_SWITCH, value: "knowledge-request-routing", persistPick: false });
});

test("outside a switch a pick is persisted for the shown thread", () => {
  const pick = chooseDuringSwitch(IDLE_THREAD_SWITCH, "coding-change-tdd");
  assert.equal(pick.persistForShownThread, true);
  assert.deepEqual(pick.state, IDLE_THREAD_SWITCH);
});

test("opening the thread already shown is no switch", () => {
  assert.deepEqual(beginThreadSwitch("thread-x", "thread-x"), IDLE_THREAD_SWITCH);
  assert.deepEqual(beginThreadSwitch("", ""), IDLE_THREAD_SWITCH);
});
