// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeExploreEntities.test.mjs
//
// The graph centres on the entity "Show in graph"
// names and hides structure nodes and literal values (X1); citations drop the internal revision and "(no link)";
// Jira wiki markup in a work item renders instead of showing raw; the empty Explore list of a new Workspace says
// what to do with one link and no error.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { graphNoise, isLiteralName, nodeNamed, withoutNoise } from "../../src/admin/components/entityGraph/entityGraphNoise.ts";
import { safeHref, wikiBlocks, wikiInline } from "../../src/chat/work/jiraWikiMarkup.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

function loader(extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Intl, setTimeout, clearTimeout, ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return (relative) => loadFile(path.join(SRC, relative));
}

test("Structure nodes and literal values are noise; real entities and the centre stay", () => {
  for (const name of ["false", "TRUE", ";", "DEFAULT", "42", "1.5", "30 s", "x", "  ", "null", "n/a"]) {
    assert.equal(isLiteralName(name), true, name);
  }
  for (const name of ["Java SE 17", "FieldDelimiter", "Acme Orders Admin Console", "server.ini", "Tomcat 10"]) {
    assert.equal(isLiteralName(name), false, name);
  }
  assert.equal(graphNoise({ node_type: "Chapter", display_name: "4.4 Database" }), "structure");
  assert.equal(graphNoise({ node_type: "Document", display_name: "Admin Guide" }), "structure");
  assert.equal(graphNoise({ node_type: "Parameter", display_name: "DEFAULT" }), "literal");
  assert.equal(graphNoise({ node_type: "Software", display_name: "Java SE 17" }), null);
  const nodes = [
    { id: "java", node_type: "Software", display_name: "Java SE 17" },
    { id: "f", node_type: "Value", display_name: "false" },
    { id: "ch", node_type: "Chapter", display_name: "2 Requirements" },
  ];
  assert.deepEqual(withoutNoise(nodes, { showNoise: false }).map((node) => node.id), ["java"]);
  assert.deepEqual(withoutNoise(nodes, { showNoise: false, keepId: "ch" }).map((node) => node.id), ["java", "ch"],
    "the entity the view is centred on is always kept");
  assert.equal(withoutNoise(nodes, { showNoise: true }).length, 3, "Advanced shows them again");
});

test("Show in graph finds its entity by the exact name only", () => {
  const nodes = [{ id: "a", display_name: "Java SE 17 Update" }, { id: "b", display_name: "java se 17" }];
  assert.equal(nodeNamed(nodes, "Java SE 17")?.id, "b");
  assert.equal(nodeNamed(nodes, "Java"), null, "no partial match");
  assert.equal(nodeNamed(nodes, ""), null);
});

test("citations drop the internal revision and '(no link)'; the full citation stays the tooltip", () => {
  const load = loader();
  const { KnowledgeCitation, readableCitation } = load("admin/components/workspaceKnowledge/KnowledgeCitation.tsx");
  assert.equal(readableCitation("Admin Guide (rev 1, p. 702, § 4.4 Database)"), "Admin Guide (p. 702, § 4.4 Database)");
  assert.equal(readableCitation("Admin Guide (p. 702, rev 3)"), "Admin Guide (p. 702)");
  assert.equal(readableCitation("Admin Guide (rev 2)"), "Admin Guide");
  let view;
  act(() => {
    view = TestRenderer.create(createElement(KnowledgeCitation, {
      title: "Admin Guide", url: null, citation: "Admin Guide (rev 1, p. 702, § 4.4 Database)",
    }));
  });
  const shown = text(view.toJSON());
  assert.equal(shown, "Admin Guide (p. 702, § 4.4 Database)");
  assert.doesNotMatch(shown, /no link|rev 1/);
  assert.equal(view.root.findByType("span").props.title, "Admin Guide (rev 1, p. 702, § 4.4 Database)");
});

test("Jira wiki markup: code, noformat, headings, lists, quotes, emphasis, underline and safe links", () => {
  const blocks = wikiBlocks([
    "h2. Steps to reproduce",
    "Start the {+}server{+} with _debug_ and *verbose* logging, see [the guide|https://wiki.example.com/x].",
    "",
    "* first",
    "* second with {{server.ini}}",
    "# one",
    "# two",
    "{code:java}",
    "public class A {",
    "  int x = 1;",
    "}",
    "{code}",
    "{noformat}raw *not bold*{noformat}",
    "bq. quoted",
    "snake_case_name stays and a - b stays",
  ].join("\n"));
  assert.deepEqual(blocks.map((block) => block.kind), ["heading", "paragraph", "list", "list", "code", "code", "quote", "paragraph"]);
  assert.equal(blocks[0].level, 2);
  assert.deepEqual(blocks[2].items.length, 2);
  assert.equal(blocks[3].ordered, true);
  assert.deepEqual([blocks[4].language, blocks[4].text], ["java", "public class A {\n  int x = 1;\n}"]);
  assert.deepEqual([blocks[5].language, blocks[5].text], ["", "raw *not bold*"], "noformat keeps its text as is");
  const inline = blocks[1].lines[0];
  assert.deepEqual(inline.map((part) => part.kind), ["text", "underline", "text", "em", "text", "strong", "text", "link", "text"]);
  assert.deepEqual(inline[7], { kind: "link", text: "the guide", href: "https://wiki.example.com/x" });
  assert.deepEqual(wikiInline("snake_case_name stays and a - b stays"), [{ kind: "text", text: "snake_case_name stays and a - b stays" }]);
  assert.deepEqual(wikiInline("[click|javascript:alert(1)]"), [{ kind: "text", text: "[click|javascript:alert(1)]" }], "no unsafe link");
  assert.equal(safeHref("mailto:ops@example.com"), "mailto:ops@example.com");
  assert.equal(safeHref("/relative"), null);
});

test("rendered Jira description: no raw markup, no HTML, code as a code block", () => {
  const load = loader();
  const { JiraWikiText } = load("chat/work/JiraWikiText.tsx");
  let view;
  act(() => {
    view = TestRenderer.create(createElement(JiraWikiText, {
      text: "Use {+}Java 17{+} and _restart_.\n{code:java}System.exit(0);{code}\n<script>alert(1)</script>",
      empty: "No Jira description captured.", testId: "work-request-text",
    }));
  });
  const shown = text(view.toJSON());
  assert.doesNotMatch(shown, /\{\+\}|\{code/);
  assert.equal(text(view.root.findByType("u")), "Java 17");
  assert.equal(text(view.root.findByType("em")), "restart");
  assert.equal(text(view.root.findByType("pre")), "System.exit(0);");
  assert.match(shown, /<script>alert\(1\)<\/script>/, "markup that is not Jira stays visible text, never HTML");
  act(() => { view.update(createElement(JiraWikiText, { text: "", empty: "No Jira description captured." })); });
  assert.equal(text(view.toJSON()), "No Jira description captured.");
});

test("empty Workspace (ux-first-run): Explore's list says what to do with one link, and shows no error", async () => {
  const fetch = async (url) => ({
    ok: true, status: 200,
    json: async () => (String(url).endsWith("/products") ? { products: {} }
      : String(url).endsWith("/graph") ? { episodes: 0, pending_revisions: 0, readable: true, extractable: true } : {}),
  });
  const load = loader({ fetch, window: { location: { origin: "https://octryx.test" } } });
  const { KnowledgeRelationshipsPanel } = load("chat/knowledge/KnowledgeRelationshipsPanel.tsx");
  const opened = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(KnowledgeRelationshipsPanel, {
      workspaceId: "ws-empty", filter: { text: "", type: "", origin: "" }, entity: "",
      onSelectEntity() {}, onFacts() {}, onBusy() {}, onOpen: (tab) => opened.push(tab),
    }));
  });
  await act(async () => {});
  const shown = text(view.toJSON());
  assert.match(shown, /No relationships extracted in this workspace yet/);
  assert.doesNotMatch(shown, /error|failed/i);
  const buttons = view.root.findAllByType("button");
  assert.equal(buttons.filter((button) => String(button.props.className).includes("--primary")).length, 0,
    "without products there is nothing to extract yet, so no primary action");
  assert.deepEqual(buttons.map((button) => text(button)), ["Open Sources"]);
  act(() => buttons[0].props.onClick());
  assert.deepEqual(opened, ["workspaceKnowledge"]);
});

test("rendered X1: Show in graph searches the name, then loads that entity's neighbourhood and hides noise", async () => {
  const calls = [];
  const node = (id, name, type = "Software") => ({ id, node_type: type, display_name: name, description: "", degree: 1, trust_level: "" });
  const graph = (nodes, edges = []) => ({
    store: "workspace_graph", workspace_id: "ws-1", state: "ok", truncated: false, nodes, edges, match_ids: null,
    stats: { shown_nodes: nodes.length, shown_edges: edges.length, total_nodes: null, total_edges: null, total_claims: null,
      total_communities: null, node_types: { Software: 1 }, edge_types: {} },
  });
  const fetch = async (url) => {
    const address = String(url);
    calls.push(address);
    const params = new URL(address, "https://octryx.test").searchParams;
    let body = {};
    if (address.includes("/explorer/nodes/")) {
      body = { state: "ok", workspace_id: "ws-1", id: "java", display_name: "Java SE 17", node_type: "Software", description: "",
        trust_level: "", status: "", properties: {}, source_refs: [], aliases: [], relations: [], claims: [] };
    } else if (params.get("focus_node_id") === "java") {
      body = graph([node("java", "Java SE 17"), node("tomcat", "Tomcat 10"), node("f", "false", "Value"), node("ch", "2 Requirements", "Chapter")],
        [{ id: "e1", source: "java", target: "tomcat", edge_type: "REQUIRES", description: "" },
          { id: "e2", source: "java", target: "f", edge_type: "HAS", description: "" },
          { id: "e3", source: "ch", target: "java", edge_type: "MENTIONS", description: "" }]);
    } else if (params.get("query") === "Java SE 17") {
      body = graph([node("java", "Java SE 17"), node("java-u", "Java SE 17 Update 3")]);
    } else {
      body = graph([node("x", "DEFAULT", "Parameter"), node("y", ";", "Value")]);
    }
    return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => body, text: async () => JSON.stringify(body) };
  };
  const load = loader({ fetch, window: { location: { origin: "https://octryx.test", href: "https://octryx.test/chat" }, addEventListener() {}, removeEventListener() {} },
    document: { addEventListener() {}, removeEventListener() {} }, requestAnimationFrame: (fn) => setTimeout(fn, 0), cancelAnimationFrame: clearTimeout });
  const { AdminEntityGraphPanel } = load("admin/components/entityGraph/AdminEntityGraphPanel.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(AdminEntityGraphPanel, { projectId: "ws-1", query: "", selectName: "Java SE 17" }));
  });
  for (let index = 0; index < 4; index += 1) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  const explorer = calls.filter((call) => call.includes("/graph/explorer?"));
  assert.match(explorer[0], /query=Java\+SE\+17/, "first the name, not the general top entities");
  assert.ok(explorer.some((call) => /focus_node_id=java(&|$)/.test(call)), "then the entity's neighbourhood");
  const shown = text(view.toJSON());
  assert.match(shown, /Tomcat 10/);
  assert.doesNotMatch(shown, /2 Requirements|\bfalse\b/, "structure and literal values are hidden by default");
  assert.match(shown, /Advanced/);
});

test("The entity panel's With column keeps a readable width next to the growing Source column", () => {
  const panel = fs.readFileSync(path.join(SRC, "chat/knowledge/explore/ExploreEntityPanel.tsx"), "utf8");
  const css = fs.readFileSync(path.join(SRC, "chat/knowledge/explore/knowledge-explore.css"), "utf8");
  assert.match(panel, /<th className="ds-table__th knowledge-explore__with" scope="col">With<\/th>/);
  assert.match(panel, /<td className="ds-table__td knowledge-explore__with">/);
  assert.match(css, /\.knowledge-explore__entity-table \.knowledge-explore__with \{ width: 12rem; min-width: 10rem; \}/);
  assert.match(css, /\.knowledge-explore__with \.knowledge-explore__link \{ overflow-wrap: break-word; \}/);
});

test("Show in graph puts the entity into the search field", () => {
  const page = fs.readFileSync(path.join(SRC, "chat/knowledge/explore/KnowledgeExplorePage.tsx"), "utf8");
  assert.match(page, /onShowInGraph=\{showInGraph\}/);
  assert.match(page, /const showInGraph = \(\) => \{\s*setState\(\(previous\) => \{ const kept = \{ \.\.\.previous, type: "", text: previous\.entity \}/);
});

test("rendered B4: with the entity as the shared term the graph still centres on it", async () => {
  const calls = [];
  const node = (id, name) => ({ id, node_type: "Software", display_name: name, description: "", degree: 1, trust_level: "" });
  const graph = (nodes) => ({
    store: "workspace_graph", workspace_id: "ws-1", state: "ok", truncated: false, nodes, edges: [], match_ids: null,
    stats: { shown_nodes: nodes.length, shown_edges: 0, total_nodes: null, total_edges: null, total_claims: null,
      total_communities: null, node_types: { Software: 1 }, edge_types: {} },
  });
  const fetch = async (url) => {
    const address = String(url);
    calls.push(address);
    const body = address.includes("/explorer/nodes/")
      ? { state: "ok", workspace_id: "ws-1", id: "java", display_name: "Java SE 17", node_type: "Software", description: "",
        trust_level: "", status: "", properties: {}, source_refs: [], aliases: [], relations: [], claims: [] }
      : graph([node("java", "Java SE 17"), node("tomcat", "Tomcat 10")]);
    return { ok: true, status: 200, headers: { get: () => "application/json" }, json: async () => body, text: async () => JSON.stringify(body) };
  };
  const load = loader({ fetch, window: { location: { origin: "https://octryx.test", href: "https://octryx.test/chat" }, addEventListener() {}, removeEventListener() {} },
    document: { addEventListener() {}, removeEventListener() {} }, requestAnimationFrame: (fn) => setTimeout(fn, 0), cancelAnimationFrame: clearTimeout });
  const { AdminEntityGraphPanel } = load("admin/components/entityGraph/AdminEntityGraphPanel.tsx");
  await act(async () => {
    TestRenderer.create(createElement(AdminEntityGraphPanel, { projectId: "ws-1", query: "Java SE 17", selectName: "Java SE 17" }));
  });
  for (let index = 0; index < 4; index += 1) await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  const explorer = calls.filter((call) => call.includes("/graph/explorer?"));
  assert.match(explorer[0], /query=Java\+SE\+17/);
  assert.ok(explorer.some((call) => /focus_node_id=java(&|$)/.test(call)), "centred on the entity");
});
