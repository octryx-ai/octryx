// Knowledge → Search reading flow (WP rework): toolbar, results rows and status strip,
// rendered through a transpile + vm harness (no browser; layout itself is unverified here).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { originalContentUrl } from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeRequest.ts";
import * as api from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeApi.ts";
import * as request from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeRequest.ts";
import * as presenter from "../../src/admin/components/workspaceKnowledge/knowledgeSearchPresenter.ts";
import * as entryModel from "../../src/chat/knowledge/knowledgeEntryModel.ts";
import * as entryStatus from "../../src/chat/knowledge/knowledgeEntryStatus.ts";
import * as searchFacets from "../../src/admin/components/workspaceKnowledge/search/searchFacets.ts";
import * as searchFamilies from "../../src/admin/components/workspaceKnowledge/search/searchFamilies.ts";
import * as snippet from "../../src/admin/components/workspaceKnowledge/search/snippet.ts";
import * as searchProgress from "../../src/admin/components/workspaceKnowledge/search/searchProgress.ts";
import * as askInChat from "../../src/admin/components/workspaceKnowledge/search/askInChat.ts";
import * as answerApi from "../../src/admin/components/workspaceKnowledge/search/answerApi.ts";
import * as dateTime from "../../src/admin/utils/dateTime.ts";
import * as SidePanel from "../../src/layout/SidePanel.ts";
import * as connectorFreshness from "../../src/admin/components/workspaceKnowledge/connectorFreshness.ts";
import * as searchStartModel from "../../src/admin/components/workspaceKnowledge/search/searchStartModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const src = fileURLToPath(new URL("../../src/", import.meta.url));
const modules = { workspaceKnowledgeApi: api, workspaceKnowledgeRequest: request, knowledgeSearchPresenter: presenter, knowledgeEntryModel: entryModel,
  knowledgeEntryStatus: entryStatus, searchFacets, searchFamilies, snippet, searchProgress, askInChat, answerApi, dateTime, SidePanel, connectorFreshness,
  searchStartModel };

// Loads a .tsx component; relative imports resolve to stubs, the pure modules above or further .tsx files.
function load(file, stubs) {
  const exports = {};
  const output = ts.transpileModule(fs.readFileSync(path.join(src, file), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  vm.runInNewContext(output, { exports, require(name) {
    if (!name.startsWith(".")) return require(name);
    if (name.endsWith(".css")) return {};
    const base = path.basename(name);
    if (stubs[base]) return stubs[base];
    if (modules[base]) return modules[base];
    const target = path.join(path.dirname(file), `${name}.tsx`);
    if (fs.existsSync(path.join(src, target))) return load(target, stubs);
    throw new Error(`unexpected import ${name} from ${file}`);
  } });
  return exports;
}

function searchStub() {
  const state = { busy: false, error: null, query: "", result: null, calls: [] };
  // Bodies are built inside the vm realm; a JSON copy compares them by value.
  state.submit = async (body) => { state.calls.push(JSON.parse(JSON.stringify(body))); };
  return { state, stubs: {
    useKnowledgeSearch: { useKnowledgeSearch: () => state },
    KnowledgeEntryOverview: { KnowledgeEntryOverview: () => null },
    useKnowledgeEntryOverview: { useKnowledgeEntryOverview: () => ({ listing: null }) },
  } };
}

const hits = [
  { evidence_key: "web", text: "Jackson 2 ".repeat(40), citation: "Spring Boot 4 release notes, rev 1", source_title: "Release notes",
    source_url: "https://docs.spring.io/notes", products: ["spring-boot"], version: "4.0", section: "Jackson" },
  { evidence_key: "own", text: "Short upload passage.", citation: "Migration guide, rev 2", source_title: "Migration guide",
    source_url: null, source_id: "s1", revision_id: "r2", products: [], version: null, section: null },
  { evidence_key: "bound", text: "Shared passage.", citation: "Team notes, rev 1", source_title: "Team notes",
    source_url: null, source_id: "s9", revision_id: "r9", products: [], version: null, section: null, bound: true, workspace: "Team B" },
];

function renderSearch(state, stubs) {
  const { KnowledgeSearchPanel } = load("admin/components/workspaceKnowledge/KnowledgeSearchPanel.tsx", stubs);
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeSearchPanel, { workspaceId: "w1", showOverview: false })); });
  return view;
}
const text = (node) => node.children.map((child) => (typeof child === "string" ? child : text(child))).join("");
const button = (view, label) => view.root.findAll((n) => n.type === "button" && text(n).startsWith(label))[0];

test("the toolbar is one labelled field with Search and an Options disclosure", () => {
  const { state, stubs } = searchStub();
  const view = renderSearch(state, stubs);
  const input = view.root.findByProps({ type: "text" });
  const label = view.root.findByProps({ htmlFor: input.props.id });
  assert.equal(label.props.htmlFor, input.props.id);
  assert.equal(text(label), "Search this workspace's sources");
  // Review: no explanatory line under the field of a Workspace with documents.
  assert.equal(input.props["aria-describedby"], undefined);
  assert.equal(text(view.root.findByType("form")).includes(presenter.searchHint(false)), false);
  assert.equal(input.props.required, true);
  assert.equal(button(view, "Search").props.disabled, true);
  act(() => input.props.onChange({ target: { value: "Jackson 2" } }));
  assert.equal(button(view, "Search").props.type, "submit");
  assert.equal(button(view, "Search").props.disabled, false);
  // Enter in a single-line field submits its form; the form sends the unchanged request.
  let prevented = false;
  act(() => view.root.findByType("form").props.onSubmit({ preventDefault: () => { prevented = true; } }));
  assert.equal(prevented, true);
  assert.deepEqual(state.calls[0], { query_text: "Jackson 2", mode: "hybrid", limit: 10, products: null, version: null });
  const options = button(view, "Options");
  const panel = view.root.findByProps({ id: options.props["aria-controls"] });
  assert.equal(options.props["aria-expanded"], false);
  assert.equal(panel.props.hidden, true);
  act(() => options.props.onClick());
  assert.equal(button(view, "Options").props["aria-expanded"], true);
  const [products, version] = panel.findAllByType("input");
  assert.equal(version.props.disabled, true);
  act(() => products.props.onChange({ target: { value: "spring-boot" } }));
  act(() => panel.findAllByType("input")[1].props.onChange({ target: { value: "4.0" } }));
  assert.equal(text(button(view, "Options")), "Options (2 active)");
  act(() => view.root.findByType("form").props.onSubmit({ preventDefault() {} }));
  assert.deepEqual(state.calls[1], { query_text: "Jackson 2", mode: "hybrid", limit: 10, products: ["spring-boot"], version: "4.0" });
  act(() => view.unmount());
});

test("Escape clears the field first and leaves it when already empty", () => {
  const { state, stubs } = searchStub();
  const view = renderSearch(state, stubs);
  const input = () => view.root.findByProps({ type: "text" });
  act(() => input().props.onChange({ target: { value: "Jackson" } }));
  let blurred = 0;
  const escape = () => ({ key: "Escape", preventDefault() {}, currentTarget: { blur: () => { blurred += 1; } } });
  act(() => input().props.onKeyDown(escape()));
  assert.equal(input().props.value, "");
  assert.equal(blurred, 0);
  act(() => input().props.onKeyDown(escape()));
  assert.equal(blurred, 1);
  act(() => input().props.onKeyDown({ key: "a" }));
  act(() => view.unmount());
});

test("results: numbered rows with title, place, a rendered passage and an Open link; no revision, offsets or score", () => {
  const { state, stubs } = searchStub();
  Object.assign(state, { query: "Jackson 2", result: { evidence: hits, mode_states: { lexical: "ok", vector: "ok", rerank: "needs_configuration" } } });
  const view = renderSearch(state, stubs);
  assert.equal(text(view.root.findByType("h2")), "3 source passages for “Jackson 2”");
  const rows = view.root.findAllByType("li");
  assert.deepEqual(rows.map((row) => text(row.findByType("h3"))), ["1Release notes", "2Migration guide", "3Team notes"]);
  // The place is section, pages or lines; never "rev 1", character offsets or "Relevance 0.62".
  assert.doesNotMatch(text(view.root), /\brev \d|chars|Relevance \d/);
  assert.match(text(rows[0]), /§ Jackson/);
  const links = rows.map((row) => row.findAllByType("a").map((a) => [text(a), a.props.href]));
  assert.deepEqual(links[0], [["Open source", "https://docs.spring.io/notes"]]);
  assert.deepEqual(links[1], [["Open original", originalContentUrl("w1", "s1", "r2")]]);
  assert.deepEqual(links[2], [], "a bound hit's original belongs to the other Workspace");
  assert.match(text(rows[2]), /Shared from Team B/);
  assert.match(text(rows[0]), /spring-boot · 4\.0/);
  // Only the long passage shows an excerpt and offers the toggle; it expands in place.
  const toggles = (row) => row.findAll((n) => n.type === "button" && /full passage|Show less/.test(text(n)));
  assert.equal(toggles(rows[1]).length, 0);
  const toggle = toggles(rows[0])[0];
  const passage = () => rows[0].findByProps({ id: toggle.props["aria-controls"] });
  const excerptLength = text(passage()).length;
  assert.ok(excerptLength < hits[0].text.trim().length, "the excerpt is shorter than the passage");
  // The question's words are marked in the excerpt.
  assert.ok(passage().findAllByType("mark").length > 0);
  act(() => toggle.props.onClick());
  assert.equal(text(toggles(rows[0])[0]), "Show less");
  assert.ok(text(passage()).length > excerptLength);
  // Preview opens the hit in a side panel; without the window the passage itself is shown.
  act(() => rows[1].findAll((n) => n.type === "button" && text(n) === "Preview")[0].props.onClick());
  assert.equal(view.root.findAllByProps({ "data-testid": "search-preview" }).length, 1);
  const availability = view.root.findByType("details");
  assert.equal(text(availability.findByType("summary")), "Search availability: 2 of 3 available");
  act(() => view.unmount());
});

test("one row per page, its further passages under \"+N more passages\", each with its preview", () => {
  const { state, stubs } = searchStub();
  const page = (key, text) => ({ evidence_key: key, text, citation: "", source_title: "Service Catalog 2022/2023",
    source_url: null, source_id: "s-offer", revision_id: "r1", products: [], version: null, section: null,
    origin: { kind: "confluence" }, container: "OPS" });
  Object.assign(state, { query: "offering", result: { evidence: [
    page("p1", "The offering covers onboarding."), hits[1], page("p2", "The offering lists deliveries."),
  ], mode_states: { lexical: "ok" } } });
  const view = renderSearch(state, stubs);
  const titles = view.root.findAll((n) => n.type === "h3" && n.props.className === "knowledge-search__hit-title");
  assert.deepEqual(titles.map(text), ["1Service Catalog 2022/2023", "2Migration guide"], "the page appears once");
  const more = view.root.findByProps({ "data-testid": "search-more-passages" });
  assert.equal(text(more), "+1 more passage");
  assert.equal(view.root.findAllByProps({ "data-testid": "search-passage" }).length, 0);
  act(() => more.props.onClick());
  const passages = view.root.findAllByProps({ "data-testid": "search-passage" });
  assert.equal(passages.length, 1);
  assert.match(text(passages[0]), /deliveries/);
  act(() => passages[0].findByType("button").props.onClick());
  const preview = view.root.findByProps({ "data-testid": "search-preview" });
  assert.match(text(preview), /deliveries/, "the folded passage opens its own preview");
  act(() => view.unmount());
});

test("busy, error and empty answers keep their status, alert and message", () => {
  const { state, stubs } = searchStub();
  Object.assign(state, { busy: true, query: "x" });
  let view = renderSearch(state, stubs);
  // The running search shows its progress, never an empty "Searching…".
  assert.match(text(view.root.findByProps({ role: "status" })), /^Searching the Workspace's sources/);
  assert.equal(view.root.findAllByProps({ "data-testid": "search-progress" }).length, 1);
  assert.equal(text(button(view, "Searching")), "Searching…");
  act(() => view.unmount());
  Object.assign(state, { busy: false, error: "Storage unavailable" });
  view = renderSearch(state, stubs);
  assert.equal(text(view.root.findByProps({ role: "alert" })), "Storage unavailable");
  act(() => view.unmount());
  Object.assign(state, { error: null, result: { evidence: [] } });
  view = renderSearch(state, stubs);
  assert.equal(text(view.root.findByType("h2")), "No source passages for “x”");
  // (frozen): the empty answer says "No matching knowledge found" and never implies verified truth.
  assert.match(text(view.root.findByProps({ className: "knowledge-search__empty" })), /^No matching knowledge found/);
  assert.equal(view.root.findAllByType("ol").length, 0);
  act(() => view.unmount());
});

const NO_SOURCES = { connectors: [] };
function renderOverview({ mayAuthor, listing, research, connectors = NO_SOURCES, isAdmin = false }) {
  const calls = [];
  const stubs = {
    adminNavigation: { useAdminNavigation: () => ({ openAdminTab: (tab) => calls.push(["open", tab]) }) },
    knowledgeEntryIntent: { requestDocumentUpload: (id) => calls.push(["upload", id]) },
    knowledgeNavigation: { keepWorkspaceInUrl: (id) => calls.push(["keep", id]) },
    useKnowledgePermissions: { useKnowledgePermissions: () => mayAuthor },
  };
  const { KnowledgeEntryOverview } = load("chat/knowledge/KnowledgeEntryOverview.tsx", stubs);
  const overview = { workspaceId: "w1", listing, sourcesFailed: false, connectors, connectorsFailed: false, research, researchFailed: false };
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeEntryOverview, { overview, isAdmin })); });
  return { view, calls };
}
const source = (id) => ({ source_id: id, source_key: id, display_title: id, revision_count: 1, latest_revision_ordinal: 1 });
const proposals = { mode: "open", sources: [{ id: "a", state: "proposed" }, { id: "b", state: "proposed" }] };

const syncedSource = (key) => ({ connector_key: key, kind: "jira", state: "active", running: false, scope: {},
  schedule: { enabled: true, interval_minutes: 360, next_run_at: null },
  cursor: { pass_number: 1, pass_started_at: null, completed_passes: 1, last_completed_at: new Date().toISOString() },
  last_run: { id: "r", state: "completed", reason: null, report: {}, started_at: null, finished_at: new Date().toISOString() } });
const SIX = { connectors: ["a", "b", "c", "d", "e", "f"].map(syncedSource), instance_scheduler_enabled: true };

test("the status strip is one short line: sources linking to Sources, their state, no numbers to explain (S5)", () => {
  const listing = { sources: [1, 2, 3, 4, 5].map((i) => source(`s${i}`)), projection_backlog: { applied: 5966 }, next_cursor: "more" };
  const { view, calls } = renderOverview({ mayAuthor: true, listing, research: proposals, connectors: SIX, isAdmin: true });
  const strip = view.root.findByProps({ className: "knowledge-entry__status" });
  assert.deepEqual(strip.findAllByType("dd").map(text), ["6 sources", "up to date"]);
  assert.equal(view.root.findAllByType("details").length, 0, "no About these numbers");
  assert.doesNotMatch(text(view.root), /documents ·|jobs|About these numbers|approved/);
  assert.deepEqual(view.root.findAllByType("button").map(text), ["6 sources", "Upload document", "Approve research websites (2)"]);
  act(() => button(view, "6 sources").props.onClick());
  assert.deepEqual(calls, [["keep", "w1"], ["open", "workspaceKnowledge"]]);
  act(() => button(view, "Upload document").props.onClick());
  assert.deepEqual(calls.slice(2), [["upload", "w1"], ["keep", "w1"], ["open", "knowledgeSources"]]);
  act(() => view.unmount());
});

test("a backlog shows muted; the count links to Sources only for those who may open it", () => {
  const listing = { sources: [source("s1")], projection_backlog: { applied: 5966, pending: 187 }, next_cursor: null };
  const { view } = renderOverview({ mayAuthor: false, listing, research: null, connectors: SIX });
  const items = view.root.findByProps({ className: "knowledge-entry__status" }).findAll((node) => node.type === "div");
  assert.deepEqual(items.map(text), ["Sources6 sources", "StateIndexing: 187 waiting"]);
  assert.match(items[1].props.className, /knowledge-entry__item--muted/);
  assert.deepEqual(view.root.findAllByType("button").map(text), ["Open documents"], "no Sources link for a non-admin");
  act(() => view.unmount());
});

test("a workspace whose source has not synced yet is not asked to connect one", () => {
  const listing = { sources: [], projection_backlog: {}, next_cursor: null };
  const { view } = renderOverview({ mayAuthor: true, listing, research: null, connectors: { connectors: [syncedSource("a")] } });
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "knowledge-first-step").length, 0);
  assert.doesNotMatch(view.root.findByType("section").props.className, /knowledge-entry--empty/);
  act(() => view.unmount());
});

test("an empty workspace keeps the first step and a reader gets read-only actions", () => {
  const listing = { sources: [], projection_backlog: {}, next_cursor: null };
  const { view } = renderOverview({ mayAuthor: false, listing, research: { mode: "trusted_only", sources: [] } });
  assert.deepEqual(view.root.findAllByType("button").map(text), ["Open documents"]);
  assert.match(text(view.root.findByType("strong")), /^First step: connect Confluence or Jira$/);
  assert.match(view.root.findByType("section").props.className, /knowledge-entry--empty/);
  act(() => view.unmount());
});

test("an empty workspace offers connecting Confluence or Jira first, upload second", () => {
  const listing = { sources: [], projection_backlog: {}, next_cursor: null };
  const { view, calls } = renderOverview({ mayAuthor: true, listing, research: { mode: "trusted_only", sources: [] } });
  const step = view.root.find((node) => node.props["data-testid"] === "knowledge-first-step");
  assert.match(text(step), /^First step: connect Confluence or Jira/);
  const connect = button(view, "Connect a source");
  assert.match(connect.props.className, /--primary/);
  assert.doesNotMatch(button(view, "Upload document").props.className, /--primary/, "upload is second");
  act(() => connect.props.onClick());
  assert.deepEqual(calls.at(-1), ["open", "workspaceKnowledge"]);
  act(() => view.unmount());
});

// ---- UI check K-Search: the area under the field was empty before the first search -----------------

const DAY = 86400000;
const connector = (key, kind, scope, overrides = {}) => ({
  connector_key: key, kind, scope, products: [], version: null, max_items_per_run: 100, state: "active",
  cursor: {}, schedule: { enabled: true, interval_minutes: 60, instance_enabled: true }, running: false,
  last_run: { state: "completed", started_at: new Date(Date.now() - DAY).toISOString(), finished_at: new Date(Date.now() - DAY).toISOString() },
  served_items: 12, ...overrides,
});
const OVERVIEW = {
  workspaceId: "w1", sourcesFailed: false, connectorsFailed: false, research: null, researchFailed: false,
  listing: { sources: [{ source_id: "d1", source_key: "k", display_title: "Runbook.pdf", revision_count: 1, latest_revision_ordinal: 1,
    origin: { type: "upload" } }], projection_backlog: {} },
  connectors: { connectors: [
    connector("eng-docs", "confluence", { spaces: ["ENG"] }),
    connector("ops-jira", "jira", { project_keys: ["OPS"] }, { last_run: { state: "failed", reason: "source_unauthorized" } }),
    connector("new-repo", "git_repository", { remote: "https://git.example/scm/acme/billing.git" }, { last_run: null, served_items: 0 }),
  ] },
};

function renderStart(state, overview = OVERVIEW) {
  const stubs = { ...searchStub().stubs, useKnowledgeSearch: { useKnowledgeSearch: () => state },
    useKnowledgeEntryOverview: { useKnowledgeEntryOverview: () => overview } };
  const { KnowledgeSearchPanel } = load("admin/components/workspaceKnowledge/KnowledgeSearchPanel.tsx", stubs);
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeSearchPanel, { workspaceId: "w1", showOverview: true })); });
  return view;
}
const byId = (view, id) => view.root.findAll((node) => node.props?.["data-testid"] === id);

test("K-Search: before a search, three example questions from the sources, a click runs one", () => {
  const { state } = searchStub();
  const view = renderStart(state);
  const examples = byId(view, "search-example").map((node) => text(node));
  // The failed Jira source still has items to find; the repository never synced, so no question about it.
  assert.deepEqual(examples, ["What is documented in ENG?", "Which OPS issues are still open?", "What does Runbook say?"]);
  act(() => byId(view, "search-example")[1].props.onClick());
  assert.equal(state.calls.length, 1);
  assert.equal(state.calls[0].query_text, "Which OPS issues are still open?");
  const input = view.root.findAll((node) => node.type === "input" && node.props.type === "text")[0];
  assert.equal(input.props.value, "Which OPS issues are still open?", "the question stays in the field to change it");
  act(() => view.unmount());
});

test("K-Search: the sources searched, each with its state and last sync; the one needing attention first", () => {
  const { state } = searchStub();
  const view = renderStart(state);
  const items = byId(view, "search-start-sources")[0].findAll((node) => node.type === "li");
  const rows = items.map((node) => text(node));
  assert.equal(rows.length, 3);
  assert.equal(rows[0], "ops-jiraJira · Needs attention");
  assert.match(items[0].props.title, /rejected the connection's credential/, "the reason is one hover away");
  assert.match(rows[1], /^eng-docsConfluence · Up to date · /);
  assert.match(rows[2], /^new-repoCode · Never synced$/);
  act(() => view.unmount());
});

test("K-Search: the start goes away once a search runs, and is not shown without sources or when embedded", () => {
  const { state } = searchStub();
  state.busy = true;
  const busy = renderStart(state);
  assert.equal(byId(busy, "search-start").length, 0);
  act(() => busy.unmount());
  const none = renderStart(searchStub().state, { ...OVERVIEW, connectors: { connectors: [] }, listing: { sources: [], projection_backlog: {} } });
  assert.equal(byId(none, "search-start").length, 0);
  act(() => none.unmount());
  const embedded = renderSearch(searchStub().state, searchStub().stubs);
  assert.equal(byId(embedded, "search-start").length, 0);
  act(() => embedded.unmount());
});
