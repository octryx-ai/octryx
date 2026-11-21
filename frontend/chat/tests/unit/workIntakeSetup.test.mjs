// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workIntakeSetup.test.mjs
//
// Work → Intake setup drawer: Source → What → When → How → Preview → Enable.
// Only the Workspace's connections are offered; projects come from the connection; the custom JQL is shown wrapped
// in the connection's projects; one schedule preset (custom cron under Advanced); discovered fields by plain name;
// the preview saves the intake (inactive) and dry-runs it; Enable comes after. Requests are stubs; names invented.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { draftPayload, intakeName, jqlPreview, newDraft, previewFacts, stepProblem, withDiscovery } from "../../src/chat/work/intake/workIntakeDraft.ts";
import { button, byTestId, load, server, text } from "./workCodingSupport.mjs";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const FOUND = {
  source_type: "jira", work_states: [{ key: "intake", label: "Intake" }, { key: "development", label: "Development" }],
  projects: [{ key: "CLM", name: "Claims" }, { key: "OPS", name: "Operations" }], issue_types: ["Bug", "Story"],
  statuses: [{ name: "To Do", state: "intake" }, { name: "In Progress", state: "development" }],
  fields: [{ role: "sprint_field", label: "Sprint", field: { id: "customfield_10020", name: "Sprint" } },
    { role: "board_field", label: "Board", field: null }],
};
const SOURCES = [
  { kind: "jira", label: "Jira", work_capable: true, connections: [{ id: "default", name: "default", scope: "workspace" }],
    knowledge: { sources: 1, last_synced_at: null }, work: null, work_state: "no_intake" },
  { kind: "confluence", label: "Confluence", work_capable: false, connections: [{ id: "default", name: "default", scope: "workspace" }],
    knowledge: null, work: null, work_state: "not_a_work_source" },
];

test("draft rules: defaults, discovery fills without overwriting, the JQL wrap, step checks, names, preview facts", () => {
  const draft = withDiscovery({ ...newDraft("jira", "default"), how: { ...newDraft("jira", "default").how, status_mapping: { "To Do": "development" } } }, FOUND);
  assert.deepEqual(draft.how.status_mapping, { "To Do": "development", "In Progress": "development" }, "a chosen mapping is kept");
  assert.deepEqual(draft.how.field_mapping, { sprint_field: "customfield_10020" });
  assert.equal(jqlPreview({ project_keys: ["CLM"], jql: "status != Done" }), "project in (CLM) AND (status != Done)");
  assert.equal(stepProblem(1, draft), "Pick at least one project.");
  assert.equal(stepProblem(2, { ...draft, schedule: { preset: "custom", cron: "" } }), "Enter the cron expression or pick a preset.");
  assert.equal(intakeName({ ...draft, what: { project_keys: ["CLM"] } }), "Jira CLM");
  assert.equal(draftPayload({ ...draft, id: "x", is_active: true }).id, undefined);
  assert.deepEqual(previewFacts({ would_import: 42, already_in_work: 0, total_source: 45, total_after_filter: 42, pending_next_run: 3,
    more_pending: true, automation: { labels: ["PRJ"], matching: 5, mode: "needs_review" } }),
  { wouldImport: 42, already: 0, skipped: null, pending: "3 pending next run", automation: "5 with label PRJ – agent may suggest", outside: "0" },
  "the limit leaves items pending; the label never skips");
  assert.deepEqual(previewFacts({ imported: 2, updated: 1, skipped_closed: 4 }),
    { wouldImport: 2, already: 1, skipped: 4, pending: "0", automation: "", outside: "0" });
});

test("rendered: the four steps, preview saves inactive then dry-runs, Enable after", async () => {
  const srv = server((url, method, body) => {
    if (url.includes("/fields?")) return { status: 200, body: FOUND };
    if (url.endsWith("/count")) return { status: 200, body: { count: 42 } };
    if (url.endsWith("/intake") && method === "POST") return { status: 200, body: { ...body, id: "in-1", is_active: false, schedule: body.schedule } };
    if (url.endsWith("/preview")) return { status: 200, body: { sync_run: { summary: { would_import: 1, already_in_work: 0, total_source: 1, total_after_filter: 1 } },
      items: [{ source_key: "CLM-214", title: "Duplicate claim", source_status: "To Do", work_state: "intake" }] } };
    if (url.endsWith("/enable")) return { status: 200, body: { first_run: {}, intake: { id: "in-1", is_active: true } } };
    return { status: 404, body: {} };
  });
  const { WorkIntakeSetupDrawer } = load("chat/work/intake/WorkIntakeSetupDrawer.tsx", { fetch: srv.fetch, setTimeout: (fn) => { fn(); return 0; }, clearTimeout: () => {} });
  const done = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkIntakeSetupDrawer, { workspaceId: "ws-1", workspaceName: "Northwind Claims", sources: SOURCES,
      target: { sourceKind: "jira" }, onClose: () => {}, onDone: (message) => done.push(message), onOpenConnectors: () => {} }));
  });
  assert.match(text(view.root), /New Jira intake/);
  const choices = view.root.findAll((node) => node.type === "button" && node.props.className?.includes("work-intake__choice"));
  assert.equal(choices.length, 1, "only work-capable connections are offered");
  await act(async () => { button(view, "Next").props.onClick(); });
  assert.equal(byTestId(view, "intake-step-1").length, 1);
  assert.equal(byTestId(view, "intake-match-count").length, 0, "no count before a project is chosen");
  assert.equal(srv.calls.filter((call) => call.url.endsWith("/count")).length, 0);
  await act(async () => { button(view, "Next").props.onClick(); });
  assert.match(text(view.root), /Pick at least one project\./);
  await act(async () => { button(view, "CLM · Claims").props.onClick(); });
  assert.match(text(byTestId(view, "intake-match-count")[0]), /42 items/);
  assert.match(text(view.root), /project in \(CLM\)/);
  await act(async () => { button(view, "Next").props.onClick(); });
  await act(async () => { view.root.findAll((node) => node.type === "button" && text(node).startsWith("Hourly"))[0].props.onClick(); });
  await act(async () => { button(view, "Next").props.onClick(); });
  assert.match(text(byTestId(view, "intake-field-sprint_field")[0]), /Sprint.*mapped/);
  assert.match(text(byTestId(view, "intake-field-board_field")[0]), /not found/);
  await act(async () => { button(view, "Run preview").props.onClick(); });
  const created = srv.calls.find((call) => call.method === "POST" && call.url.endsWith("/intake"));
  assert.deepEqual(created.body.schedule, { preset: "hourly", cron: null });
  assert.equal(created.body.name, "Jira CLM");
  assert.match(text(byTestId(view, "intake-preview-facts")[0]), /Would import1.*Already in Work0/);
  assert.match(text(view.root), /CLM-214.*Duplicate claim.*To Do.*Intake/);
  assert.match(text(view.root), /Enable starts the first run now and then hourly\./);
  await act(async () => { button(view, "Enable intake").props.onClick(); });
  assert.deepEqual(done, ["Intake enabled. The first run started."]);
  act(() => view.unmount());
});
