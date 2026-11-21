// Render guards for the Observability pages split into smaller functions: the overview tiles and lists, the
// decisions timeline with its filters and pages, and the audit log with its detail drawer render the same structure.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, createAsync, includesAll } from "./adminGuardRenderers.mjs";
import { jsonRoutes, loadStubbed, stubs } from "./adminGuardStubLoader.mjs";

const navigation = (opened) => ({ useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) });

test("the observability overview shows the tiles, what needs attention and the health strip", async () => {
  const opened = [];
  const assigned = [];
  const window = { location: { search: "", assign: (href) => assigned.push(href) } };
  const { ObservabilityOverviewPage } = loadStubbed("admin/components/observability/ObservabilityOverviewPage.tsx", [], { window },
    { adminNavigation: navigation(opened) });
  const payload = {
    checked_at: "2026-03-04T05:06:07Z",
    attention: [
      { severity: "danger", label: "2 failing", title: "Indexer", cause: "Disk full", age: "3 h", action: "Open runs", link: { tab: "usage" } },
      { severity: "attention", label: "waiting", title: "Approval", cause: "Nobody decided", age: "1 d", action: "Decide", link: { href: "/x" } },
    ],
    health: { summary: { ok: 4, failing: 0, degraded: 2, unknown: 1, disabled: 0 }, strip: [
      { key: "db", label: "Database", status: "ok", counts: {}, detail: "–" },
      { key: "q", label: "Queue", status: "degraded", counts: { degraded: 2 }, detail: "slow" },
    ] },
    spend: { month_spend: 12.5, priced_coverage: 0.75, since: "2026-03-01T00:00:00Z" },
    decisions_today: { by_outcome: { denied: 3 }, total: 3, allowed: 9 },
  };
  const { readJson, calls } = jsonRoutes({ "/api/v1/observability/overview": payload });
  const view = await createAsync(createElement(ObservabilityOverviewPage, { projects: [], readJson }));
  includesAll(text(view.root), ["Checked", "Refresh", "Needs attention", "2", "1 failing · 1 waiting", "Health", "2 degraded",
    "2 degraded · 1 unknown · 4 ok", "Spend · March", "25 % of tokens unpriced → the real figure is higher", "Decisions · today", "3 denied",
    "Each item opens the page where it is fixed.", "Indexer", "Disk full", "Open runs →", "Decide →", "Health at a glance", "Open Health",
    "Database", "Queue", "slow"]);
  assert.equal(view.root.findAll((node) => node.props.className === "ob-tile").length, 4);
  assert.equal(view.root.findAll((node) => node.props.className === "ob-item").length, 2);
  assert.equal(all(view, "button").length, 4 + 1 + 2 + 1 + 2);
  assert.equal(view.root.findAll((node) => node.props.className === "ob-muted" && text(node) === "–").length, 0);
  act(() => all(view, "button").find((node) => text(node) === "Open runs →").props.onClick());
  act(() => all(view, "button").find((node) => text(node) === "Decide →").props.onClick());
  act(() => all(view, "button").find((node) => text(node) === "Open Health").props.onClick());
  assert.deepEqual(opened, ["usage", "observabilityHealth"]);
  assert.deepEqual(assigned, ["/x"]);
  assert.equal(calls.length, 1);

  const empty = await createAsync(createElement(ObservabilityOverviewPage, { projects: [], readJson: jsonRoutes({
    "/api/v1/observability/overview": { ...payload, attention: [], spend: { ...payload.spend, priced_coverage: 1 } } }).readJson }));
  includesAll(text(empty.root), ["Nothing needs attention. Last checked", "all platform-billed tokens are priced", "nothing needs attention"]);
  const failed = await createAsync(createElement(ObservabilityOverviewPage, { projects: [], readJson: async () => { throw new Error("down"); } }));
  assert.equal(failed.root.findAll((node) => node.props.role === "alert").length, 1);
  assert.equal(failed.root.findAll((node) => node.props.className === "ob-tiles").length, 0);
});

test("the decisions page lists decisions with filters, pages, approval links and the drawers", async () => {
  const { ObservabilityDecisionsPage } = loadStubbed("admin/components/observability/ObservabilityDecisionsPage.tsx",
    ["./DecisionDrawer", "./RunDrawer"], { window: { location: { search: "?policy=pol-1&decision=d-9" } } });
  const items = [
    { id: "d1", time: "2026-03-04T05:06:07Z", outcome: "denied", gate: "cedar", action: "a", what: "Write file", subtitle: "Too wide",
      who: "Ann", decided_by: null, workspace_id: "w1", workspace_name: "Harbor", rule: "no-writes", reason: null, approval_id: "ap-1" },
    { id: "d2", time: null, outcome: "approved", gate: "x_gate", action: "b", what: "Deploy", who: "Bob", decided_by: "Cleo",
      workspace_id: null, workspace_name: null, rule: null, reason: null },
  ];
  const { readJson, calls } = jsonRoutes({
    "/api/v1/observability/decisions/today": { by_outcome: {}, total: 0, allowed: 1234 },
    "/api/v1/observability/decisions": { window_hours: 168, page: 1, page_size: 1, total: 2, items },
  });
  const view = await createAsync(createElement(ObservabilityDecisionsPage, { projects: [{ id: "w1", name: "Harbor" }], readJson }));
  includesAll(text(view.root), ["Every non-allow outcome of every gate", "allowed today", "Showing the decisions of policy", "pol-1",
    "Show all", "Write file", "Approval ›", "Too wide", "Ann · Harbor", "Policy (Cedar)", "no-writes", "Deploy", "by Cleo · global",
    "–", "2 decisions in the window", "Page 1 of 2", "All gates"]);
  assert.deepEqual(all(view, "th").map((node) => text(node)), ["Time", "Outcome", "What", "Who · where", "Gate", "Deciding rule"]);
  assert.equal(all(view, "tr").length, 3);
  assert.equal(byTestId(view, "decision-approval-link")[0].props.href.includes("ap-1"), true);
  assert.equal(stubs(view, "DecisionDrawer")[0].props.decisionId, "d-9");
  assert.ok(calls[0].url.includes("policy_id=pol-1"));
  const next = () => all(view, "button").find((node) => text(node) === "Next");
  assert.equal(next().props.disabled, false);
  await act(async () => next().props.onClick());
  await tick();
  assert.ok(text(view.root).includes("Page 2 of 2"));
  act(() => stubs(view, "DecisionDrawer")[0].props.onOpenRun("run-1"));
  assert.equal(stubs(view, "DecisionDrawer").length, 0);
  assert.equal(stubs(view, "RunDrawer")[0].props.runKey, "run-1");
  act(() => all(view, "tr")[2].props.onKeyDown({ key: "Enter" }));
  assert.equal(stubs(view, "DecisionDrawer")[0].props.decisionId, "d2");
  await act(async () => all(view, "button").find((node) => text(node) === "Show all").props.onClick());
  await tick();
  assert.ok(!text(view.root).includes("Showing the decisions of policy"));
  assert.ok(text(view.root).includes("Page 1 of 2"));
  assert.ok(buttons(view).includes("Previous"));

  const none = await createAsync(createElement(ObservabilityDecisionsPage, { projects: [], readJson: jsonRoutes({
    "/api/v1/observability/decisions/today": { by_outcome: {}, total: 0, allowed: 0 },
    "/api/v1/observability/decisions": { window_hours: 168, page: 1, page_size: 50, total: 0, items: [] } }).readJson }));
  includesAll(text(none.root), ["No decisions match. Allowed requests are counted, not listed.", "Page 1 of 1"]);
});

test("the audit log lists changes, filters them and opens one in its drawer", async () => {
  const { ObservabilityAuditPage } = loadStubbed("admin/components/observability/ObservabilityAuditPage.tsx", ["../projectsTab/SettingsDrawer"]);
  const items = [
    { id: "a1", time: "2026-03-04T05:06:07Z", actor: "Ann", change: "PUT /api/v1/x", object: "policy · p-1", category: "policy",
      ip_address: "10.0.0.1", details: { before: { a: 1 }, after: { a: 2 } } },
    { id: "a2", time: null, actor: "Bob", change: "user.created", object: null, category: "users", ip_address: null, details: {} },
  ];
  const { readJson, calls } = jsonRoutes({ "/api/v1/observability/audit?": { window_days: 30, categories: ["policy", "users"], page: 1,
    page_size: 50, total: 2, items } });
  const view = await createAsync(createElement(ObservabilityAuditPage, { projects: [], readJson }));
  includesAll(text(view.root), ["Export", "Ann", "PUT /api/v1/x", "Policy", "p-1", "Bob", "–", "2 changes in the last 30 days", "Page 1 of 1"]);
  assert.deepEqual(all(view, "th").map((node) => text(node)), ["Time", "Actor", "Change", "Object", "Category"]);
  assert.equal(all(view, "tr").length, 3);
  assert.equal(all(view, "code").length, 2);
  assert.equal(calls[0].url, "/api/v1/observability/audit?window_days=30&page=1");
  act(() => all(view, "tr")[1].props.onClick());
  const drawer = stubs(view, "SettingsDrawer")[0];
  assert.ok(drawer.props.title.startsWith("Ann · "));
  assert.ok(drawer.props.eyebrow.endsWith(" · policy"));
  includesAll(text(drawer), ["Actor", "When", "From", "10.0.0.1", "Category", "Object", "policy · p-1", "Change"]);
  assert.equal(drawer.findAll((node) => node.type === "pre").length, 1);
  act(() => drawer.props.onClose());
  assert.equal(stubs(view, "SettingsDrawer").length, 0);
  await act(async () => all(view, "input")[0].props.onChange({ target: { value: "ann" } }));
  await tick(300);
  assert.ok(calls.at(-1).url.includes("q=ann"));

  const none = await createAsync(createElement(ObservabilityAuditPage, { projects: [], readJson: jsonRoutes({ "/api/v1/observability/audit?":
    { window_days: 7, categories: [], page: 1, page_size: 50, total: 0, items: [] } }).readJson }));
  assert.ok(text(none.root).includes("No administrative changes match in this window."));
});
