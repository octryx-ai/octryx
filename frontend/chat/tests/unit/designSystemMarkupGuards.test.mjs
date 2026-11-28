// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/designSystemMarkupGuards.test.mjs
//
// Design system guards for rules that live in markup and stylesheets rather than in a rendered flow (the rendered ones are tested next to their pages).
import assert from "node:assert/strict";
import fs from "node:fs";
import { test } from "node:test";

import { checkTypeLabel } from "../../src/admin/components/agentsWorkflows/canvas/checkTypeLabels.ts";
import { costSourceLabel, gatewayCodeText, modelGroupFieldLabel, responseShapeLabel } from "../../src/admin/components/providerTab/litellmGatewayWords.ts";
import { diagnosticsWords, effectiveSourceWords } from "../../src/admin/components/researchPolicies/researchProfileSummary.ts";
import { providerDisplayName, providerSummary } from "../../src/chat/knowledge/researchSourceRows.ts";

const read = (relative) => fs.readFileSync(new URL(`../../src/${relative}`, import.meta.url), "utf8");

test("390 px: Admin's menu is hidden like every area's sub-navigation; its entries are in the compact menu", () => {
  const shell = read("styles/chat/admin-panel-narrow.css");
  const narrow = shell.slice(shell.indexOf("@media (max-width: 860px)"));
  assert.match(narrow, /\.admin-panel--admin \.admin-panel__sidebar \{\s*display: none;/);
  const menu = read("chat/CompactAreaMenu.tsx");
  assert.match(menu, /ADMIN_ENTRIES\.map/);
  assert.match(menu, /onSelectAdminTab\(entry\.tab\)/);
});

test("MCP servers follow the global Workspace switch; the page has no Workspace selector of its own", () => {
  const tab = read("admin/components/AdminMcpTab.tsx");
  assert.ok(!tab.includes("<AdminMcpWorkspaceSelect") && !tab.includes("WorkspaceScopeSelect"));
  assert.match(tab, /useActiveWorkspace\(workspaceOptions\)/);
  assert.match(read("admin/components/AdminMcpWorkspaceSelect.tsx"), /<ChooseWorkspaceLine/);
});

test("one table header style: no stylesheet sets an uppercase column header any more", () => {
  const files = [];
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = new URL(`${entry.name}${entry.isDirectory() ? "/" : ""}`, dir);
      if (entry.isDirectory()) walk(full); else if (entry.name.endsWith(".css")) files.push(full);
    }
  };
  walk(new URL("../../src/", import.meta.url));
  const found = [];
  for (const file of files) {
    const css = fs.readFileSync(file, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");
    for (const rule of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      if (!/text-transform:\s*uppercase/.test(rule[2])) continue;
      // A column header: a th of the table head (a group row inside the body, .sk-fam, is not one).
      const headers = rule[1].split(",").map((part) => part.trim()).filter((part) => /(^|[\s>])th($|[\s:.[])|__th\b|thead/.test(part) && !/tr\.sk-fam/.test(part));
      if (headers.length) found.push(`${file.pathname.split("/src/")[1]}: ${headers.join(", ")}`);
    }
  }
  assert.deepEqual(found, []);
});

test("raw values read as words: gateway, research, workflow checks", () => {
  assert.equal(responseShapeLabel("openai_model_list"), "OpenAI model list");
  assert.equal(modelGroupFieldLabel("model_name"), "Model name");
  assert.equal(costSourceLabel("catalog_pricing"), "Priced here");
  assert.equal(gatewayCodeText("endpoint_host_allowlist_not_configured"), "List at least one allowed host.");
  assert.equal(gatewayCodeText("something_new"), "Something new.", "an unknown code reads as words, never as the code");
  assert.equal(providerDisplayName("tavily"), "Tavily");
  assert.equal(providerSummary({ name: "tavily", state: "ok", quarantine_reason: null, data_policy_class: null }).text,
    "Search provider: Tavily · Working");
  assert.equal(effectiveSourceWords("default_profile"), "the platform's default profile");
  assert.equal(diagnosticsWords("valid"), "", "a valid check says nothing");
  assert.equal(diagnosticsWords("invalid_version"), " · check: invalid version");
  assert.equal(checkTypeLabel("tool_called"), "A tool was called");
  assert.equal(checkTypeLabel("judge"), "Judge (advisory)");
  assert.equal(checkTypeLabel("brand_new_check"), "Brand new check");
});

test("the check editor shows no bare JSON", () => {
  const inspector = read("admin/components/agentsWorkflows/canvas/StepsInspector.tsx");
  assert.match(inspector, /Technical details/);
  assert.match(inspector, /checkTypeLabel\(item\)/);
});
