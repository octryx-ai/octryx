import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  acceptsGraphPayload, GRAPH_LAYERS, graphExplorerUrl, toggleGraphLayer,
} from "../../src/admin/components/entityGraph/entityGraphPresentation.ts";
import { reportUrl, structuredBase } from "../../src/admin/components/workspaceKnowledge/structuredGraphApi.ts";
import {
  buildSummary, citationLocation, displayValue, layerRows, reportNotice, reportSummary, runnerSummary, toggleLayer,
  variantsNote,
} from "../../src/admin/components/workspaceKnowledge/structuredGraphModel.ts";
import * as links from "../../src/chat/evidence/answerSourceLinks.ts";
import * as api from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeApi.ts";
import * as request from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeRequest.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

test("the explorer sends a layer selection only when it narrows the view", () => {
  const all = GRAPH_LAYERS.map((layer) => layer.id);
  const full = new URL(graphExplorerUrl("ws", "", "", 50, all), "https://local.test");
  assert.equal(full.searchParams.get("layers"), null);
  const narrow = new URL(graphExplorerUrl("ws", "MaxConnections", "", 50, ["manual", "configuration"]), "https://local.test");
  assert.equal(narrow.searchParams.get("layers"), "manual,configuration");
  assert.equal(narrow.searchParams.get("query"), "MaxConnections");
});

test("layer toggles keep the fixed order and never empty the selection", () => {
  assert.deepEqual(toggleGraphLayer(["operations"], "manual"), ["manual", "operations"]);
  assert.deepEqual(toggleGraphLayer(["manual", "operations"], "manual"), ["operations"]);
  assert.deepEqual(toggleGraphLayer(["operations"], "operations"), ["operations"]);
  assert.deepEqual(toggleLayer(["operations"], "manual"), ["manual", "operations"]);
  assert.deepEqual(toggleLayer(["manual"], "manual"), []);
});

test("the explorer accepts the combined store and the extracted-only store, for this workspace only", () => {
  assert.equal(acceptsGraphPayload({ store: "workspace_graph", workspace_id: "a" }, "a"), true);
  assert.equal(acceptsGraphPayload({ store: "extracted_graph", workspace_id: "a" }, "a"), true);
  assert.equal(acceptsGraphPayload({ store: "workspace_graph", workspace_id: "b" }, "a"), false);
  assert.equal(acceptsGraphPayload({ store: "other", workspace_id: "a" }, "a"), false);
});

test("report requests stay inside the workspace and send only set filters", () => {
  assert.equal(structuredBase("w/1"), "/api/v1/workspaces/w%2F1/knowledge/graph/structured");
  const url = new URL(reportUrl("w", { parameter: " MaxConnections ", file: "", section: "4.4.12" }), "https://local.test");
  assert.equal(url.pathname, "/api/v1/workspaces/w/knowledge/graph/structured/report");
  assert.equal(url.searchParams.get("parameter"), "MaxConnections");
  assert.equal(url.searchParams.get("file"), null);
  assert.equal(url.searchParams.get("section"), "4.4.12");
});

test("status and report wording is explicit about builds, gaps and redaction", () => {
  assert.match(buildSummary(undefined), /No structured graph/);
  const completed = { state: "completed", layers: ["manual", "configuration"], failure: null,
    report: { layers: { manual: { extracted: 2 }, configuration: { extracted: 30, failed: 1 } } } };
  assert.equal(buildSummary(completed), "Last build of Manual, Configuration completed: 32 source revisions extracted, 1 unreadable.");
  assert.match(buildSummary({ ...completed, state: "failed", failure: "build_failed" }), /failed \(build_failed\)/);
  assert.equal(buildSummary({ ...completed, state: "running", lease_expired: false }), "Build of Manual, Configuration is running.");
  assert.match(buildSummary({ ...completed, state: "running", lease_expired: true }), /waiting to be resumed/);
  assert.match(runnerSummary(null), /not reported yet/);
  assert.equal(runnerSummary({ status: "success", updated_at: "2026-10-07T10:00:00", completed_at: null, failure: null }),
    "The build runner last reported at 2026-10-07T10:00:00.");
  assert.match(runnerSummary({ status: "failed", updated_at: "t", failure: "runtime_unavailable" }),
    /problem at t \(runtime_unavailable\)/);
  const rows = layerRows({ layers: { manual: { revisions: 2, nodes: 10, edges: 12 } } });
  assert.deepEqual(rows.map((row) => row.text), ["2 sources · 10 nodes · 12 relationships", "not built", "not built"]);
  // A reader who is not an author gets no counts (they include restricted sources) and no report.
  assert.equal(buildSummary({ ...completed, report: null }), "Last build of Manual, Configuration completed.");
  assert.deepEqual(layerRows({ counts_visible: false, layers: null }).map((row) => row.text),
    Array(3).fill("counts are shown to workspace authors"));
  assert.match(reportNotice({ state: "not_built" }), /Build the configuration layer/);
  assert.equal(reportNotice({ state: "ok" }), null);
  assert.equal(displayValue("s3cr3t", true), "[redacted]");
  assert.equal(citationLocation({ source_title: "Acme Orders Server 3.2 Manual", page: 212, section: "4.4.12 Redis Connection" }),
    "Acme Orders Server 3.2 Manual · p. 212 · § 4.4.12 Redis Connection");
  assert.equal(citationLocation({ source_title: "conf/server.ini", line: 29 }), "conf/server.ini · line 29");
  assert.equal(citationLocation(null), "citation not available to you");
});

function loadCitation() {
  const exports = {};
  const source = fs.readFileSync(new URL("../../src/admin/components/entityGraph/EntityGraphCitation.tsx", import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports, window: { location: { origin: "https://local.test" } }, require(name) {
      if (name.endsWith("answerSourceLinks")) return links;
      if (name.endsWith("workspaceKnowledgeApi")) return api;
      if (name.endsWith("workspaceKnowledgeRequest")) return request;
      return require(name);
    },
  });
  return exports.EntityGraphCitation;
}

test("a structured citation shows its manual page or file line and opens the captured source", () => {
  const Citation = loadCitation();
  let view;
  act(() => { view = TestRenderer.create(createElement(Citation, { workspaceId: "ws", evidence: {
    citation: "acme-orders-server-ini:conf/server.ini (rev 1, lines 1-30)", line: 29, source_id: "s", revision_id: "r",
    source_url: "https://git.example.com/conf/server.ini#L29",
  } })); });
  const text = JSON.stringify(view.toJSON());
  assert.match(text, /line /);
  assert.match(text, /29/);
  const anchors = view.root.findAllByType("a");
  assert.equal(anchors[0].props.href, "/api/v1/workspaces/ws/knowledge/sources/s/revisions/r/original");
  act(() => view.unmount());
  act(() => { view = TestRenderer.create(createElement(Citation, { workspaceId: "ws", evidence: {
    citation: "Acme Orders Server 3.2 Manual (rev 1, p. 212)", page: 212, section: "4.4.12 Redis Connection",
  } })); });
  const manual = JSON.stringify(view.toJSON());
  assert.doesNotMatch(manual, /p\. ",?212/);  // the page already in the citation text is not repeated
  assert.match(manual, /4\.4\.12 Redis Connection/);
  act(() => view.unmount());
});

test("the report summary separates known-section gaps, unknown sections and unresolved placeholders", () => {
  const counts = { configured_settings: 1624, undocumented_in_known_section: 368, unknown_section: 1237,
    unknown_section_settings: 5927, deviations: 479, unresolved_placeholders: 7, inconsistencies: 120,
    documented_unused: 338 };
  assert.equal(reportSummary({ counts, truncated: true }),
    "1624 settings match a documented parameter · 368 undocumented in sections the manual knows · "
    + "1237 sections unknown to the manual (5927 keys) · 479 deviate from the default · 7 unresolved placeholders · "
    + "120 differ across components · 338 documented but never set (lists show the first items).");
  assert.match(reportSummary({ counts: {}, truncated: false }), /^0 settings match .* 0 documented but never set\.$/);
  assert.equal(variantsNote([]), null);
  assert.equal(variantsNote(undefined), null);
  assert.equal(variantsNote([
    { path: "worker/app.ini-test", variant: "test", line: 4, value: "700" },
    { path: "worker/app.ini-prod", variant: "prod", line: 4, value: "${Timeout}", resolved_value: "500" },
  ]), "also worker/app.ini-test line 4: 700; worker/app.ini-prod line 4: ${Timeout} = 500");
});
