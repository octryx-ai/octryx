// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workIntakeOverview.test.mjs
//
// Work → Intake: the per-Workspace overview (Connection · In Knowledge ·
// In Work), the "connected and in Knowledge but no intake" gap, each intake's What/When/How/Connection, and its run
// history from `…/intake/{id}/runs`. Requests are stubs; names are invented.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  automationLabel,
  connectionLabel,
  gapSource,
  scheduleLabel,
  whatLabel,
  workSourcesSummary,
} from "../../src/chat/work/intake/workIntakeModel.ts";
import { connectorMonogram, hasBrandGlyph } from "../../src/admin/components/connectorMonogram.ts";
import { button, byTestId, load, server, text } from "./workCodingSupport.mjs";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const JIRA = { kind: "jira", label: "Jira", work_capable: true, connections: [{ id: "default", name: "default", scope: "workspace" }],
  knowledge: { sources: 1, last_synced_at: null }, work: null, work_state: "no_intake" };
const SN = { kind: "servicenow", label: "ServiceNow", work_capable: true, connections: [{ id: "c-1", name: "sn-prod", scope: "workspace" }],
  knowledge: null, work: { intakes: 1, active: 1, items: 3, last_run_at: null, last_run_status: "completed" }, work_state: "set_up" };
const WIKI = { kind: "confluence", label: "Confluence", work_capable: false, connections: [], knowledge: { sources: 1, last_synced_at: null },
  work: null, work_state: "not_a_work_source" };
const INTAKE = { id: "in-1", name: "Claims incidents", source_type: "servicenow", is_active: true,
  connection: { id: "c-1", name: "sn-prod", available: true }, what: { tables: ["incident"], excluded_states: ["Closed", "Resolved"], custom_query: false },
  schedule: { preset: "every_15_min", cron: null }, automation_mode: null, automation_labels: ["PRJ"], items: 3,
  last_run_at: null, last_run_status: "completed" };
const RUNS = [
  { id: "r-2", status: "completed", mode: "sync", trigger: "scheduled", completed_at: "2026-10-08T10:15:00Z", summary: { imported: 1, unchanged: 2 } },
  { id: "r-1", status: "failed", mode: "sync", trigger: "manual", completed_at: "2026-10-08T09:45:00Z", summary: { code: "servicenow_auth_failed" } },
];

test("model: summary, gap, connection, schedule, automation and what in plain words", () => {
  assert.equal(workSourcesSummary([JIRA, SN, WIKI]), "1 of 2 work sources set up");
  assert.equal(gapSource([JIRA, SN])?.kind, "jira", "connected and in Knowledge, no intake");
  assert.equal(gapSource([{ ...JIRA, knowledge: null }]), null, "not in Knowledge: no gap note");
  assert.equal(connectionLabel({ name: "default", scope: "global" }), "Default connection (global)");
  assert.equal(scheduleLabel({ preset: "daily_0600", cron: null }), "Daily 06:00");
  assert.equal(scheduleLabel({ preset: "custom", cron: "*/30 * * * *" }), "Custom: */30 * * * *");
  assert.equal(automationLabel({ automation_mode: "direct", automation_labels: ["PRJ"] }), "Agent may start (label PRJ)");
  assert.equal(automationLabel({ automation_mode: null, automation_labels: [] }), "Suggest only");
  assert.equal(whatLabel(INTAKE), "incident · excluding Closed, Resolved");
  assert.equal(whatLabel({ source_type: "jira", what: { project_keys: ["CLM"], issue_types: ["Bug", "Story"] } }), "Project CLM · Bug, Story");
});

test("rendered: the overview, the gap note, the intake card and its run history; Set up opens the drawer; Connect links out", async () => {
  const srv = server((url) => (url.endsWith("/runs")
    ? { status: 200, body: { runs: RUNS } }
    : { status: 200, body: { project_id: "ws-1", sources: [JIRA, SN, WIKI], intakes: [INTAKE] } }));
  const { WorkIntakePage } = load("chat/work/intake/WorkIntakePage.tsx", { fetch: srv.fetch });
  const connectors = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkIntakePage, { workspaceId: "ws-1", workspaceName: "Northwind Claims",
      onOpenConnectors: () => connectors.push(1) }));
  });
  assert.equal(srv.calls[0].url, "/api/v1/secure-work/workspaces/ws-1/intake");
  assert.match(text(view.root), /Sources of Northwind Claims/);
  assert.match(text(byTestId(view, "intake-source-jira")[0]), /✗ no intake/);
  assert.match(text(byTestId(view, "intake-source-confluence")[0]), /not a work source/);
  const brands = view.root.findAll((node) => node.props.className === "connector-brand-icon").map((node) => node.props["data-brand"]);
  assert.deepEqual(brands.slice(0, 2), ["jira", "confluence"], "real logos where simple-icons has one");
  const monograms = view.root.findAll((node) => node.props.className === "connector-brand-icon connector-brand-icon--monogram");
  assert.ok(monograms.length >= 1, "ServiceNow has no brand glyph: a neutral monogram tile");
  assert.equal(monograms[0].props["aria-label"], "ServiceNow");
  assert.equal(text(monograms[0]), "SN");
  assert.match(text(view.root), /Jira is connected and synced into Knowledge, but nothing flows into Work yet\./);
  await act(async () => { button(view, "Set up Jira intake").props.onClick(); });
  assert.match(text(view.root), /New Jira intake/, "Set up opens the setup drawer on that source");
  await act(async () => { view.root.findAll((node) => node.props["aria-label"] === "Close")[0].props.onClick(); });
  assert.doesNotMatch(text(view.root), /New Jira intake/);
  const card = byTestId(view, "intake-card")[0];
  assert.match(text(card), /via sn-prod/);
  assert.match(text(card), /Every 15 min/);
  assert.match(text(card), /Suggest only/);
  const rows = byTestId(view, "intake-run");
  assert.equal(rows.length, 2);
  assert.match(text(rows[0]), /scheduled.*completed.*1 imported · 2 unchanged/);
  assert.match(text(rows[1]), /manual.*failed.*servicenow_auth_failed/);
  await act(async () => { view.root.findAll((node) => node.type === "button" && text(node) === "connections")[0].props.onClick(); });
  assert.equal(connectors.length, 1);
  act(() => view.unmount());
});

test("connectors without a brand glyph share one monogram fallback", () => {
  assert.equal(connectorMonogram("ServiceNow"), "SN");
  assert.equal(connectorMonogram("Azure DevOps"), "AD");
  assert.equal(connectorMonogram("servicenow"), "S");
  assert.equal(connectorMonogram("  "), "?");
  const glyphs = { jira: "J", servicenow: "generic" };
  assert.equal(hasBrandGlyph("jira", glyphs), true);
  assert.equal(hasBrandGlyph("servicenow", glyphs), false, "the generic stand-in is not a brand glyph");
  assert.equal(hasBrandGlyph("topdesk", glyphs), false);
});
