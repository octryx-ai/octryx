// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceModels.test.mjs
//
// Workspace → Models — one list by display name, greyed models above
// the level, an explicit default among the allowed chat models, and the seat card with company models in /model.
import assert from "node:assert/strict";
import { test } from "node:test";

import { act, byTestId, change, click, render, server, text, tick } from "./settingsRenderHarness.mjs";
import {
  contractProblems,
  saveErrorText,
  readWorkspaceModels,
  setMode,
  toggleModel,
} from "../../src/admin/components/workspaceModels/workspaceModelsModel.ts";

const PAYLOAD = () => ({
  contract: { mode: "all_cleared", selected: [], default: null, task_overrides: {},
    seat: { mode: "forbidden", subscription_models: ["claude-sonnet-5"], company_models_in_seat: false } },
  models: [
    { key: "octryx-general", label: "General model", provider: "Company gateway", gateway: true, cleared_up_to: "internal",
      approved_for: [], temperature: null, cleared: true, reason: "", used_in: ["chat", "coding_tools", "device_runs"], allowed: true },
    { key: "nova-lite", label: "Nova 2 Lite", provider: "AWS Bedrock", gateway: false, cleared_up_to: null, approved_for: [],
      temperature: 0.2, cleared: true, reason: "", used_in: ["chat"], allowed: true },
    { key: "octryx-secret", label: "Restricted model", provider: "Company gateway", gateway: true, cleared_up_to: "public",
      approved_for: [], temperature: null, cleared: false, reason: "cleared only up to Public", used_in: ["coding_tools"], allowed: false },
  ],
  level: "internal",
  seat_checks: { seat_allowed_at_level: true, company_model_allowed: true },
});

test("the contract: switching to selected keeps what is allowed; a default must stay allowed", () => {
  const view = readWorkspaceModels(PAYLOAD());
  const selected = setMode(view.contract, view.models, "selected");
  assert.deepEqual(selected.selected, ["octryx-general", "nova-lite"], "only cleared models, nothing changes yet");
  const withDefault = { ...selected, default: "nova-lite" };
  const cleared = toggleModel(withDefault, "nova-lite", false);
  assert.equal(cleared.default, null, "un-ticking the default clears it");
  assert.deepEqual(contractProblems({ ...selected, selected: ["octryx-secret"] }, view.models), ["Pick at least one model for chat & agents."]);
});

test("rendered Workspace → Models: tick and default go out as the contract; both seat values are read-only and never sent", async () => {
  const srv = server((call) => {
    if (call.url.includes("/data-classification/policy")) return { status: 200, body: { levels: [{ level: "internal", label: "Internal", color: "internal" }, { level: "public", label: "Public", color: "public" }] } };
    if (call.method === "PUT") return { status: 200, body: { ...PAYLOAD(), contract: { ...PAYLOAD().contract, ...call.body } } };
    return { status: 200, body: PAYLOAD() };
  });
  const view = await render("admin/components/workspaceModels/WorkspaceModelsSection.tsx", "WorkspaceModelsSection", srv, { projectId: "w1" });
  try {
    const table = text(byTestId(view, "workspace-models-table")[0]);
    assert.match(table, /General model.*Chat & agents.*Coding tools.*Device runs.*Internal/);
    assert.match(table, /Restricted model.*not allowed here: cleared only up to Public/);
    assert.doesNotMatch(table, /runtime-target:/);
    assert.equal(byTestId(view, "workspace-model-allow-octryx-secret")[0].props.disabled, true);
    await act(async () => { view.root.findAll((node) => node.props.type === "radio" && node.props.value === "selected")[0].props.onChange(); });
    await act(async () => { byTestId(view, "workspace-model-allow-nova-lite")[0].props.onChange({ target: { checked: false } }); });
    await change(view, "workspace-default-model", "octryx-general");
    assert.equal(view.root.findAll((node) => node.props.type === "radio" && /^seat-mode-/.test(node.props.name ?? "")).length, 0,
      "no seat mode choice on this page");
    assert.equal(text(byTestId(view, "workspace-seat-mode-value")[0]), "Off");
    assert.equal(byTestId(view, "workspace-seat-mode-link")[0].props.href, "/chat?area=agents&workspace_id=w1&agents_view=classification");
    assert.equal(text(byTestId(view, "workspace-seat-company-value")[0]), "Off");
    const link = byTestId(view, "workspace-seat-company-link")[0];
    assert.equal(text(link), "Changed in Agents › Seats & data classification");
    assert.equal(link.props.href, "/chat?area=agents&workspace_id=w1&agents_view=classification");
    assert.equal(view.root.findAll((node) => node.props.role === "switch").length, 0, "no switch for a seat key on this page");
    await click(view, "workspace-models-save");
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.ok(put.url.endsWith("/api/v1/admin/workspaces/w1/models"));
    assert.deepEqual(put.body, { mode: "selected", selected: ["octryx-general"], default: "octryx-general", task_overrides: {} },
      "no seat key in the save body");
    assert.match(text(view.root), /Models saved/);
  } finally { act(() => view.unmount()); }
});

test("a seat key change through the wrong card is refused by the server in words that point to the seat card", () => {
  assert.equal(saveErrorText({ status: 422, code: "seat_setting_via_seat_route" }),
    "Not saved: seat settings are changed in Agents › Seats & data classification.");
});

test("task models: a Workspace picks an allowed model per task; un-allowing it falls back to the platform", async () => {
  const { setTaskModel } = await import("../../src/admin/components/workspaceModels/workspaceModelsModel.ts");
  const view = readWorkspaceModels({ ...PAYLOAD(), contract: { ...PAYLOAD().contract, mode: "selected", selected: ["octryx-general", "nova-lite"],
    task_overrides: { summarize: "nova-lite" } }, tasks: [{ key: "summarize", label: "Conversation summaries", platform_model: "octryx-general" }] });
  assert.deepEqual(view.contract.task_overrides, { summarize: "nova-lite" });
  assert.equal(view.tasks[0].platformModel, "octryx-general");
  const withMemory = setTaskModel(view.contract, "memory", "octryx-general");
  assert.deepEqual(setTaskModel(withMemory, "memory", "").task_overrides, { summarize: "nova-lite" }, "empty = platform default");
  assert.deepEqual(toggleModel(withMemory, "nova-lite", false).task_overrides, { memory: "octryx-general" });
});
