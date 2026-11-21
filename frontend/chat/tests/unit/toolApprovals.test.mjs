// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/toolApprovals.test.mjs
//
// Settings → Security → Tool & approval policies — the platform default and each Workspace's
// additions (approval_policy), plus the read-only MCP overview.
import assert from "node:assert/strict";
import { test } from "node:test";

import { act, byTestId, change, click, render, server, text, tick } from "./settingsRenderHarness.mjs";
import { policySummary, toolLabel, workspaceSummary } from "../../src/admin/components/toolApprovals/toolApprovalsModel.ts";

const PAYLOAD = () => ({
  default: { require_for_risks: ["admin"], require_for_tools: ["send_email"], exempt_tools: [] },
  risks: ["read", "write", "admin", "unknown"],
  tools: [{ name: "send_email", risk: "write" }, { name: "create_jira_issue", risk: "write" }, { name: "web_search", risk: "read" }],
  workspaces: [{ id: "w1", name: "Harbor", mode: "inherit", own: { require_for_risks: [], require_for_tools: [], exempt_tools: [] }, effective: {} }],
  mcp: { servers: ["docs-search"], workspaces: [{ id: "w1", name: "Harbor", servers: { "docs-search": true } }] },
});

test("approval rules in words", () => {
  assert.equal(toolLabel("create_jira_issue"), "Create jira issue");
  assert.equal(toolLabel("mcp__docs__search"), "MCP docs · search");
  assert.equal(policySummary({ require_for_risks: ["admin", "write"], require_for_tools: ["a"], exempt_tools: [] }), "Admin, Write risk, plus 1 tool");
  assert.equal(workspaceSummary({ mode: "add", own: { require_for_risks: [], require_for_tools: ["send_email"], exempt_tools: [] } }), "Default + Send email");
  assert.equal(workspaceSummary({ mode: "inherit", own: { require_for_risks: [], require_for_tools: [], exempt_tools: [] } }), "Platform default");
});

test("rendered Tool & approval policies: a Workspace adds a tool to the default; the MCP overview is read-only", async () => {
  const srv = server((call) => ({ status: 200, body: PAYLOAD() }));
  const view = await render("admin/components/toolApprovals/ToolApprovalsPage.tsx", "ToolApprovalsPage", srv);
  try {
    assert.match(text(byTestId(view, "approval-default")[0]), /Admin.*Send email/);
    await click(view, "approval-edit-w1");
    await act(async () => { view.root.findAll((node) => node.props.type === "radio" && node.props.value === "add")[0].props.onChange(); });
    const adminRisk = view.root.findAll((node) => node.props.type === "checkbox")[2];
    assert.equal(adminRisk.props.disabled, true, "the default's risk cannot be removed here");
    await change(view, "approval-always-select", "create_jira_issue");
    await click(view, "approval-always-add");
    await click(view, "approval-save");
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.ok(put.url.endsWith("/api/v1/admin/tool-approvals/workspaces/w1"));
    assert.deepEqual(put.body, { mode: "add", require_for_risks: [], require_for_tools: ["create_jira_issue"], exempt_tools: [] });
    await click(view, "subtab-mcp");
    assert.match(text(byTestId(view, "approval-mcp")[0]), /Harbor.*On/);
    assert.equal(view.root.findAll((node) => node.type === "select" && node.props["data-testid"]?.startsWith?.("mcp")).length, 0);
  } finally { act(() => view.unmount()); }
});
