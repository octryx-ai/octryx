import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import {
  EMPTY_FILTERS,
  complianceQuery,
  detailEntries,
  eventTypeLabel,
  hiddenFieldsText,
  outcomeTone,
} from "../../src/admin/components/observability/complianceAuditModel.ts";
import { TestRenderer, act, byTestId, flush, loader, text, windowStub } from "./adminFlowRenderHarness.mjs";

test("compliance query carries only the set filters and the cursor", () => {
  assert.equal(complianceQuery(EMPTY_FILTERS, null), "limit=50");
  const search = new URLSearchParams(complianceQuery({ ...EMPTY_FILTERS, workspaceId: "ws-1", eventType: "admin_change" }, "abc"));
  assert.equal(search.get("workspace_id"), "ws-1");
  assert.equal(search.get("event_type"), "admin_change");
  assert.equal(search.get("cursor"), "abc");
  assert.equal(search.has("since"), false);
});

test("the date range covers whole local days, the end day included", () => {
  const search = new URLSearchParams(complianceQuery({ ...EMPTY_FILTERS, from: "2026-11-02", to: "2026-11-03" }, null));
  assert.equal(new Date(search.get("since")).getTime(), new Date(2026, 10, 2).getTime());
  assert.equal(new Date(search.get("until")).getTime(), new Date(2026, 10, 4).getTime());
});

test("details read as key and value, and the hidden fields only as a count", () => {
  assert.deepEqual(detailEntries({ action: "created", revision: 3 }), [
    { key: "action", value: "created" }, { key: "revision", value: "3" }]);
  assert.equal(hiddenFieldsText(0), null);
  assert.equal(hiddenFieldsText(1), "1 more field hidden");
  assert.equal(hiddenFieldsText(3), "3 more fields hidden");
});

test("kinds read as words and outcomes never rely on an unknown tone", () => {
  assert.equal(eventTypeLabel("knowledge_promotion"), "Knowledge promotion");
  assert.equal(outcomeTone("blocked"), "danger");
  assert.equal(outcomeTone("allowed"), "active");
  assert.equal(outcomeTone(null), "neutral");
});

const RECORD = (id, extra = {}) => ({
  id, created_at: "2026-11-24T10:00:00", event_type: "admin_change", outcome: "allowed",
  workspace: { id: "ws-1", name: "Payments" }, actor: { id: "u-1", display_name: "Release manager" }, actor_role: "admin",
  resource_type: "mcp_server", resource_id: "srv-1", resource_name: "Tracker", details: {}, hidden_field_count: 0,
  classification_level: null, request_id: null, session_id: null, ...extra,
});

async function renderPage() {
  const drawer = { SettingsDrawer: ({ title, children }) => createElement("aside", { "data-testid": "drawer" }, title, children) };
  const load = loader({ window: windowStub() }, { "/projectsTab/SettingsDrawer": drawer });
  const { ComplianceAuditPage } = load("admin/components/observability/ComplianceAuditPage.tsx");
  const calls = [];
  const readJson = async (url) => {
    calls.push(url);
    if (url.endsWith("/kinds")) return { event_types: ["admin_change"], workspaces: [{ id: "ws-1", name: "Payments" }], platform_admin: true };
    if (url.includes("cursor=c1")) {
      return { records: [RECORD("r3", { details: { action: "created" }, hidden_field_count: 2 })], next_cursor: null };
    }
    return { records: [RECORD("r1"), RECORD("r2", { workspace: null, actor: null })], next_cursor: "c1" };
  };
  let view;
  await act(async () => { view = TestRenderer.create(createElement(ComplianceAuditPage, { readJson })); });
  await flush();
  return { root: view.root, calls };
}

const rows = (root) => root.findAll((node) => node.type === "tr" && node.props.tabIndex === 0);

test("the page lists records, loads more by cursor and shows the hidden fields as a count", async () => {
  const { root, calls } = await renderPage();
  assert.equal(rows(root).length, 2);
  assert.match(text(rows(root)[1]), /Platform.*System/);

  await act(async () => { byTestId(root, "compliance-more")[0].props.onClick(); });
  await flush();
  assert.ok(calls.some((url) => url.includes("cursor=c1")));
  assert.equal(rows(root).length, 3);
  assert.equal(byTestId(root, "compliance-more").length, 0);

  await act(async () => { rows(root)[2].props.onClick(); });
  const drawerText = text(byTestId(root, "drawer")[0]);
  assert.match(drawerText, /action.*created/);
  assert.match(drawerText, /2 more fields hidden/);
});

test("a late answer for old filters neither replaces nor extends the rows of the new ones", async () => {
  const load = loader({ window: windowStub() }, { "/projectsTab/SettingsDrawer": { SettingsDrawer: () => null } });
  const { ComplianceAuditPage } = load("admin/components/observability/ComplianceAuditPage.tsx");
  const pending = [];
  const readJson = (url) => {
    if (url.endsWith("/kinds")) return Promise.resolve({ event_types: ["admin_change"], workspaces: [], platform_admin: true });
    return new Promise((resolve) => pending.push({ url, resolve }));
  };
  let view;
  await act(async () => { view = TestRenderer.create(createElement(ComplianceAuditPage, { readJson })); });
  await flush();
  const kind = view.root.find((node) => node.type === "select" && node.props["aria-label"] === "Kind");
  await act(async () => { kind.props.onChange({ target: { value: "admin_change" } }); });
  await flush();
  const [stale, fresh] = pending;
  assert.ok(!stale.url.includes("event_type") && fresh.url.includes("event_type=admin_change"));

  await act(async () => { fresh.resolve({ records: [RECORD("new", { resource_name: "Fresh" })], next_cursor: null }); });
  await act(async () => { stale.resolve({ records: [RECORD("old-1"), RECORD("old-2")], next_cursor: "c-old" }); });
  await flush();
  assert.deepEqual(rows(view.root).map((row) => text(row).includes("Fresh")), [true]);
  assert.equal(byTestId(view.root, "compliance-more").length, 0, "the old cursor is not offered");
});
