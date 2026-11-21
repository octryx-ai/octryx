// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/commandSafety.test.mjs
//
// Settings → Security → Command safety — one page, one save, Workspace Inherit / Override.
import assert from "node:assert/strict";
import { test } from "node:test";

import { act, byTestId, change, click, render, server, text, tick } from "./settingsRenderHarness.mjs";

const GATE = () => ({
  checks: [
    { key: "exec_policy", label: "Blocked command patterns", description: "d", outcomes: ["block", "ask"], enabled: true },
    { key: "llm_risk", label: "AI risk review", description: "d", outcomes: ["ask", "block"], enabled: false },
  ],
  llm_risk: { timeout_seconds: 8, review_threshold: 40, deny_threshold: 80, review_model: "" },
  lists: { always_deny_patterns: ["mkfs"], commands: ["ls"], git: ["log"], kubectl: ["get"], operators: ["&&"] },
});

function gateServer() {
  let stored = { ...GATE(), guard_rules: [], custom_guard_rules: [],
    workspaces: [{ id: "w1", name: "Harbor", mode: "inherit", differences: [] }] };
  return server((call) => {
    if (call.url.endsWith("/command-safety/workspaces/w1")) {
      if (call.method === "PUT") return { status: 200, body: { mode: call.body.mode } };
      return { status: 200, body: { mode: "inherit", settings: GATE(), differences: [] } };
    }
    if (call.method === "PUT") {
      stored = { ...stored, checks: stored.checks.map((check) => ({ ...check, enabled: call.body.checks[check.key] })),
        llm_risk: { ...stored.llm_risk, ...call.body.llm_risk }, lists: call.body.lists };
    }
    return { status: 200, body: stored };
  });
}

test("rendered Command safety: a check, a score of 0 and a new pattern go out in one payload", async () => {
  const srv = gateServer();
  const view = await render("admin/components/commandSafety/CommandSafetyPage.tsx", "CommandSafetyPage", srv);
  try {
    assert.equal(byTestId(view, "command-save")[0].props.disabled, true, "nothing changed yet");
    await act(async () => { byTestId(view, "command-check-llm_risk")[0].props.onClick(); });
    await change(view, "command-review_threshold", "0");
    await change(view, "command-deny-input", "terraform destroy");
    await click(view, "command-deny-add");
    await click(view, "command-save");
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.ok(put.url.endsWith("/api/v1/admin/command-safety"));
    assert.deepEqual(put.body.checks, { exec_policy: true, llm_risk: true });
    assert.equal(put.body.llm_risk.review_threshold, 0);
    assert.deepEqual(put.body.lists.always_deny_patterns, ["mkfs", "terraform destroy"]);
    assert.match(text(view.root), /Command safety saved/);
  } finally { act(() => view.unmount()); }
});

test("rendered Command safety: a Workspace overrides with the same form, or inherits", async () => {
  const srv = gateServer();
  const view = await render("admin/components/commandSafety/CommandSafetyPage.tsx", "CommandSafetyPage", srv);
  try {
    assert.match(text(byTestId(view, "command-workspaces")[0]), /Harbor.*Inherit/);
    await click(view, "command-workspace-w1");
    await tick();
    await click(view, "command-workspace-save");
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT" && call.url.endsWith("/workspaces/w1"));
    assert.deepEqual(put.body, { mode: "inherit" });
  } finally { act(() => view.unmount()); }
});

test("rendered Command safety: defaults and an admin's own entries read apart, removed defaults are named", async () => {
  // "defaults must work": the stored list never hides a later default; the page says which is which.
  const gate = { ...GATE(), lists: { ...GATE().lists, commands: ["ls", "tree"] },
    list_origins: { commands: { defaults: ["ls", "cd"], removed_defaults: ["cd"] }, git: { defaults: ["log"], removed_defaults: [] } },
    guard_rules: [], custom_guard_rules: [], workspaces: [] };
  const srv = server(() => ({ status: 200, body: gate }));
  const view = await render("admin/components/commandSafety/CommandSafetyPage.tsx", "CommandSafetyPage", srv);
  try {
    assert.equal(text(byTestId(view, "command-commands-origin-ls")[0]), "default");
    assert.equal(text(byTestId(view, "command-commands-origin-tree")[0]), "added");
    assert.equal(text(byTestId(view, "command-git-origin-log")[0]), "default");
    assert.match(text(byTestId(view, "command-commands-removed")[0]), /cd/);
    assert.equal(byTestId(view, "command-git-removed").length, 0);
  } finally { act(() => view.unmount()); }
});
