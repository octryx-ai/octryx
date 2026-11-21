// Chat on a device: the send body of a device target blanks every Server-only selection, the target is
// sticky per thread, and the live job block rebuilds the current turn from sequenced events without gaps.
import assert from "node:assert/strict";
import { test } from "node:test";

import { buildChatSendBody } from "../../src/chat/chatSendPayload.ts";
import {
  adoptNewThreadTarget,
  readExecutionTarget,
  setExecutionTarget,
} from "../../src/chat/devices/executionTarget.ts";
import { applyJobEvent, jobState, readJob, readJobs, restoresDeviceTarget } from "../../src/chat/devices/deviceJobsModel.ts";
import { turnView } from "../../src/chat/devices/deviceTurnView.ts";

const selection = {
  sessionId: "", projectId: "ws-1", runtimeTargetId: "rt-1", thinkingLevel: "light", routingOverridesEnabled: true,
  agentId: "ag-1", workflowKey: "triage",
};

test("a device target sends execution_target and no Server-only selection", () => {
  const body = buildChatSendBody("Run the tests", {
    ...selection,
    executionTarget: { kind: "device", deviceId: "dev_a", folder: "/home/sample/src", profile: "seat" },
  });
  assert.deepEqual(body.execution_target, { kind: "device", device_id: "dev_a", folder: "/home/sample/src",
    profile: "seat", model: "", permission_mode: "", effort: "" });  // The device's defaults
  for (const key of ["workflow_key", "runtime_target_id", "agent_id"]) {
    assert.equal(body[key] ?? "", "", key);
  }
  const server = buildChatSendBody("Hi", { ...selection, executionTarget: { kind: "server" } });
  assert.equal("execution_target" in server, false);
  assert.equal(server.runtime_target_id, "rt-1");
});

test("the target is sticky per thread and a new thread keeps its choice", () => {
  setExecutionTarget(null, { kind: "device", deviceId: "dev_a", folder: "/f", profile: "governed" });
  assert.equal(readExecutionTarget("s-other").kind, "server");
  adoptNewThreadTarget("s-new");
  assert.equal(readExecutionTarget("s-new").kind, "device");
  assert.equal(readExecutionTarget(null).kind, "server");
});

test("a device choice never outlives its new chat", () => {
  setExecutionTarget("s-known", { kind: "device", deviceId: "dev_a", folder: "/f", profile: "seat", model: "m" });
  setExecutionTarget(null, { kind: "device", deviceId: "dev_b", folder: "/g", profile: "seat", model: "claude-opus-5-5" });
  adoptNewThreadTarget("s-known"); // the thread already had its own target (opened while the send ran)
  assert.equal(readExecutionTarget("s-known").deviceId, "dev_a");
  assert.equal(readExecutionTarget(null).kind, "server"); // the next new chat: Server, Workspace default
});

test("a thread reopens on its device only while it still runs there", () => {
  const idle = readJob({ id: "dj_1", device_id: "dev_a", profile: "seat", status: "idle", requested_model: "m" });
  const live = readJob({ id: "dj_1", device_id: "dev_a", profile: "seat", status: "running" });
  const device = { role: "assistant", model: "device:seat" };
  const server = { role: "assistant", model: "" }; // e.g. the Server's execution-gate answer
  assert.equal(restoresDeviceTarget(idle, [{ role: "user" }, device]), true);
  assert.equal(restoresDeviceTarget(idle, [{ role: "user" }]), true);
  assert.equal(restoresDeviceTarget(idle, [device, { role: "user" }, server]), false);
  assert.equal(restoresDeviceTarget(live, [server]), true);
  assert.equal(restoresDeviceTarget(undefined, [device]), false);
  // Since a device answer names its model; the server marks it with origin "device".
  const named = { role: "assistant", model: "claude-haiku-5-5", origin: "device" };
  assert.equal(restoresDeviceTarget(idle, [{ role: "user" }, named]), true);
  assert.equal(restoresDeviceTarget(idle, [{ role: "user" }, { role: "assistant", model: "gemma-4-31b" }]), false);
});

test("a job the launcher ended after the CI pipeline is done, not rejected", () => {
  const ended = readJob({ id: "dj_2", device_id: "dev_a", profile: "seat", status: "rejected", status_reason: "pipeline_done" });
  assert.deepEqual(jobState(ended, null), { label: "Done: CI pipeline ran", tone: "done", live: false });
  const idle = readJob({ id: "dj_3", device_id: "dev_a", profile: "seat", status: "idle", status_reason: "pipeline_done" });
  assert.equal(jobState(idle, null).tone, "done");
});

const job = (overrides = {}) => ({ id: "dj_1", device_id: "dev_a", device_name: "Laptop", folder: "/f",
  profile: "governed", status: "running", turn_id: "t1", last_event_seq: 1, ...overrides });

test("events build the current turn; a gap asks for a reload", () => {
  let jobs = readJobs({ items: [{ ...job(), events: [{ seq: 1, type: "job_accepted", body: { turn_id: "t1" } }],
    approvals: [] }] });
  const event = (seq, body, type = "job_event") => ({ job: job({ last_event_seq: seq }), seq, eventType: type,
    body: { turn_id: "t1", ...body } });
  jobs = applyJobEvent(jobs, event(2, { kind: "text_delta", text: "Work" }));
  jobs = applyJobEvent(jobs, event(3, { kind: "text_delta", text: "ing" }));
  jobs = applyJobEvent(jobs, event(4, { kind: "tool_use", tool: "Bash", tool_use_id: "u1", input_preview: "pytest" }));
  jobs = applyJobEvent(jobs, event(5, { kind: "tool_result", tool_use_id: "u1", is_error: true, output: "1 failed" }));
  jobs = applyJobEvent(jobs, event(5, { kind: "tool_result", tool_use_id: "u1", output: "dup" }));
  const view = turnView(jobs[0]);
  assert.deepEqual(view.items.map((item) => item.kind === "text" ? item.text : `${item.tool}:${item.status}`),
    ["Working", "Bash:error"]);
  assert.equal(applyJobEvent(jobs, event(9, { kind: "text" })), null);
  const approval = { job: job(), eventType: "approval_request", seq: 6, body: {},
    approval: { id: "da_1", tool: "Edit", status: "pending", can_allow_job_edits: true, expires_at: null } };
  assert.equal(applyJobEvent(jobs, approval)[0].approvals[0].canAllowJobEdits, true);
});

test("job states say what happened in words", () => {
  const [rejected] = readJobs({ items: [{ ...job({ status: "rejected", status_reason: "folder_not_allowlisted_on_device" }),
    events: [], approvals: [] }] });
  assert.equal(jobState(rejected, null).label, "Not started: the folder is not allowed on the device");
  const [idle] = readJobs({ items: [{ ...job({ status: "idle" }), events: [], approvals: [] }] });
  assert.equal(jobState(idle, { status: "stopped" }).label, "Stopped");
  assert.equal(jobState(idle, { status: "success" }).tone, "done");
});

test("a restarted or stalled turn says it was interrupted; a blocked folder names the next step", () => {
  for (const reason of ["service_restarted", "turn_stalled"]) {
    const [idle] = readJobs({ items: [{ ...job({ status: "idle", status_reason: reason }), events: [], approvals: [] }] });
    assert.equal(jobState(idle, { status: "failed", reason }).label, "Interrupted — send again");
  }
  const [blocked] = readJobs({ items: [{ ...job({ status: "rejected", status_reason: "device_folder_not_accessible" }),
    events: [{ seq: 1, type: "job_rejected", body: { reason: "device_folder_not_accessible", os: "macos",
      service_python: "/opt/homebrew/bin/python3.12" } }], approvals: [] }] });
  const label = jobState(blocked, null).label;
  assert.match(label, /macOS blocks the background service from /);
  assert.match(label, /Full Disk Access \/ Files & Folders for \/opt\/homebrew\/bin\/python3\.12, or use a folder in your home/);
  const [timedOut] = readJobs({ items: [{ ...job({ status: "idle", status_reason: "claude_initialize_timeout" }),
    events: [], approvals: [] }] });
  assert.match(jobState(timedOut, { status: "error", error: "claude_initialize_timeout" }).label,
    /^Ended: Claude Code on the device did not start in time/);
});
