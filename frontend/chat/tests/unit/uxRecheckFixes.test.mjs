// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/uxRecheckFixes.test.mjs
//
// The UX re-check: guards for the fixes that live in markup and
// stylesheets rather than in a rendered flow (the rendered ones are tested next to their pages).
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";
import { readCssWithImports } from "./cssWithImports.mjs";

const read = (relative) => fs.readFileSync(new URL(`../../src/${relative}`, import.meta.url), "utf8");

test("The policy table fits its frame; narrow frames hide low-priority columns instead of scrolling sideways", () => {
  const css = read("admin/components/policyEngine/policiesTable.css").replace(/\/\*[\s\S]*?\*\//g, "");
  const wrap = css.slice(css.indexOf(".policies__table-wrap {"), css.indexOf("}", css.indexOf(".policies__table-wrap {")));
  assert.doesNotMatch(wrap, /overflow-x:\s*auto/, "no sideways scroll");
  assert.match(wrap, /container-type:\s*inline-size/);
  assert.match(css, /\.policies__table \{\s*table-layout: fixed;/);
  assert.doesNotMatch(css, /min-width:\s*(14|22)rem/, "no fixed column minimum wider than the page");
  // First Scope and Updated step back, then Effect, then Status; Name, the sentence and ⋯ always stay.
  const steps = [...css.matchAll(/@container policies-table \(max-width: (\d+)px\) \{([\s\S]*?)\n\}/g)].map((match) => [Number(match[1]), match[2]]);
  assert.deepEqual(steps.map(([width]) => width), [880, 640, 440]);
  assert.match(steps[0][1], /col-scope,\s*\.policies__table \.policies__col-updated \{ display: none; \}/);
  assert.match(steps[1][1], /col-effect \{ display: none; \}/);
  assert.match(steps[2][1], /col-status \{ display: none; \}/);
  for (const [, body] of steps) assert.doesNotMatch(body, /col-(name|sentence|menu) \{ display: none/);
  const list = read("admin/components/policyEngine/PolicyList.tsx");
  const headers = [...list.matchAll(/<th scope="col" className="policies__col-(\w+)"/g)].map((match) => match[1]);
  assert.deepEqual(headers, ["name", "effect", "sentence", "scope", "status", "updated", "menu"]);
  assert.match(list, /className="policies__name" title=\{item\.description \? `\$\{item\.name\} — \$\{item\.description\}` : item\.name\}/,
    "a cut name keeps its full text as the tooltip");
});

test("one field label style: no stylesheet sets an uppercase form field label (sentence case like table headers)", () => {
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, dir);
      if (entry.isDirectory()) walk(full); else if (entry.name.endsWith(".css")) files.push(full);
    }
  };
  walk(new URL("../../src/", import.meta.url));
  // A field label: a label or legend element, the span of a design-system field (admin-panel__field > span), or a
  // class named like one (connector-field__label, admin-panel__form-label, admin-form-field__label, …__presets-label of
  // a form). Section titles, eyebrows and badges are not field labels.
  const fieldLabel = (selector) => /(^|[\s>+~])(label|legend)($|[\s.:#[>+~])/.test(selector)
    || /field[\w-]*\s*>?\s*span\b/.test(selector) || /field[\w-]*__label\b|[.-]form-label\b|[.-]form(-\w+)?__[\w-]*label\b|shell__label\b/.test(selector);
  const found = [];
  for (const file of files) {
    const css = fs.readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!/text-transform:\s*uppercase/.test(rule[2])) continue;
      const labels = rule[1].split(",").map((part) => part.trim()).filter(fieldLabel);
      if (labels.length) found.push(`${file.pathname.split("/src/")[1]}: ${labels.join(", ")}`);
    }
  }
  assert.deepEqual(found, []);
});

test("field labels are written in sentence case, not Title Case", () => {
  const PROPER = new Set(["Jira", "Confluence", "ServiceNow", "URL", "API", "ID", "OpenID", "Connect", "MCP", "AWS", "GitHub", "GitLab",
    "Bitbucket", "Workspace", "Workspaces", "Knowledge", "LiteLLM", "SSO", "OIDC", "JSON", "SQL", "DSN", "TLS", "Kubernetes", "Cloud",
    "Atlassian", "Data", "Center", "Server", "Slack", "Teams", "Bedrock", "Azure", "OpenAI", "Ollama", "Cedar", "Claude", "Code", "Git"]);
  const label = /className="(?:admin-panel__field|admin-form-field|connector-field__label|admin-panel__form-label|admin-form-field__label)[^"]*"[^>]*>\s*(?:<span[^>]*>\s*)?([^<{]+?)\s*[<{]/g;
  const found = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, dir);
      if (entry.isDirectory()) { walk(full); continue; }
      if (!entry.name.endsWith(".tsx")) continue;
      for (const match of fs.readFileSync(full, "utf8").matchAll(label)) {
        const words = match[1].trim().split(/\s+/).filter((word) => /^[A-Za-z]/.test(word));
        if (words.length > 6) continue; // a hint, not a label
        const titled = words.slice(1).filter((word) => /^[A-Z][a-z]/.test(word) && !PROPER.has(word.replace(/[^\w]/g, "")));
        if (titled.length) found.push(`${full.pathname.split("/src/")[1]}: ${match[1].trim()}`);
      }
    }
  };
  walk(new URL("../../src/", import.meta.url));
  assert.deepEqual(found, []);
});

test("raw values: the chat names the model in words; the raw id stays the tooltip", async () => {
  const { modelDisplayName } = await import("../../src/chat/header/runDetailsFacts.ts");
  assert.equal(modelDisplayName("anthropic.claude-haiku-5-5"), "Claude Haiku 5.5");
  assert.equal(modelDisplayName("us.anthropic.claude-sonnet-4-5-20250929-v1:0"), "Claude Sonnet 4.5");
  assert.equal(modelDisplayName("gemma-4"), "Gemma 4");
  assert.equal(modelDisplayName("Automatic · Gemma 4 (Frankfurt)"), "Automatic · Gemma 4 (Frankfurt)", "words stay words");
  const header = read("chat/WorkspaceHeader.tsx");
  assert.match(header, /: lastUsed\s*\? modelDisplayName\(modelShortLabel\(lastUsed\)\)/);
  assert.match(header, /lastUsed \? `Model used: \$\{lastUsed\}`/);
  const shell = readCssWithImports(new URL("../../src/styles/chat/workspace-shell.css", import.meta.url)).replace(/\/\*[\s\S]*?\*\//g, "");
  const line = shell.slice(shell.indexOf(".workspace__context-line {"), shell.indexOf("}", shell.indexOf(".workspace__context-line {")));
  assert.doesNotMatch(line, /uppercase/, "names as they are written, not an uppercase eyebrow");
});

test("minors: the selected segment scrolls into view; Work filters use a chevron, not a literal v", async () => {
  const { scrollToShow } = await import("../../src/layout/SegmentedTabs.ts");
  assert.equal(scrollToShow(0, 360, 480, 90), 226, "a tab right of the view scrolls in with a margin");
  assert.equal(scrollToShow(300, 360, 100, 90), 84, "a tab left of the view scrolls back");
  assert.equal(scrollToShow(100, 360, 200, 90), 100, "a visible tab leaves the row where it is");
  const tabs = read("layout/SegmentedTabs.ts");
  assert.match(tabs, /useEffect\(\(\) => \{[\s\S]*scrollToShow\([\s\S]*\}, \[value\]\);/);
  const filters = read("chat/work/WorkFilters.tsx");
  assert.doesNotMatch(filters, /aria-hidden="true">v</);
  assert.match(filters, /className=\{`work-filter-multi__chevron/);
});

test("panels carry no explanatory text: upload steps and the webhook timestamp note are in the help", () => {
  const upload = read("admin/components/workspaceKnowledge/KnowledgeUploadFields.tsx");
  assert.doesNotMatch(upload, /<ol className="knowledge-upload__steps">/);
  assert.match(upload, /<span className="ds-sr-only">\{processingSteps/);
  const help = fs.readFileSync(new URL("../../help/knowledge/knowledgeSources.md", import.meta.url), "utf8");
  assert.match(help, /\*\*Uploaded\*\*: the original is stored unchanged/);
  const drawer = read("admin/components/inboundWebhooks/InboundWebhookDetailSections.tsx");
  assert.match(drawer, />\s*Accept calls without a signed timestamp\s*</);
  assert.match(fs.readFileSync(new URL("../../help/admin/webhooks.md", import.meta.url), "utf8"), /Repeats of the same call within 5 minutes are still refused/);
});
