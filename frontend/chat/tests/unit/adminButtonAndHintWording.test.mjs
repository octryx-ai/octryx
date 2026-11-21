// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminButtonAndHintWording.test.mjs
// The minor findings: sentence case on buttons, a Cancel is never the bright primary button, the
// Channels empty line names the real button, "All workspaces" stays on one line, a hint under a field is a sentence
// (not an uppercase label), and the tabs of a source's side panel repeat no raw key as a heading.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const ADMIN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin/components");
const read = (file) => fs.readFileSync(path.join(ADMIN, file), "utf8");

test("New user is in sentence case, without a \"+\" (UI set: action labels carry no symbol)", () => {
  assert.match(read("usersTab/AdminUserAccountsPanel.tsx"), /"New user"/);
  assert.doesNotMatch(read("usersTab/AdminUserAccountsPanel.tsx"), /New User/);
});

test("Add provider and Register OIDC provider open a side panel; the header button never turns into Cancel", () => {
  for (const [file, open, panel] of [["usersTab/AdminIdentityProvidersPanel.tsx", "showCreate", "<SidePanel"],
    ["AdminProvidersTab.tsx", "showAddProvider", "<AddProviderForm"], ["providerTab/AddProviderForm.tsx", "showAddProvider", "<SidePanel"]]) {
    const source = read(file);
    assert.doesNotMatch(source, new RegExp(`${open} \\? "Cancel"`), `${file}: no header button that turns into Cancel`);
    assert.ok(source.includes(panel), `${file}: creates in a side panel`);
  }
});

test("New profile from template opens a side panel; the header button never turns into Cancel", () => {
  const source = read("AdminCorpIdentityTab.tsx");
  assert.doesNotMatch(source, /showNewProfile \? "Cancel"/);
  assert.match(source, /<SidePanel title="New corporate identity profile"/);
});

test("the Channels empty line offers the same Add channel as the page header", () => {
  assert.match(read("AdminChannelsTab.tsx"), /\{availableLoading \? "Loading…" : "Add channel"\}/);
  assert.match(read("AdminChannelCardList.tsx"), /label: "Add channel", onClick: onAdd/);
});

test("Available in keeps one line in the Connections table", () => {
  assert.match(read("connections/ConnectionsPage.tsx"), /\{ key: "available", header: "Available in", nowrap: true,/);
});

test("a hint under a connection field is a sentence, not an uppercase label", () => {
  const css = read("connections/connections.css");
  const rule = css.match(/\.connections__field > \.connections__fact,\s*\.connections__field > \.connections__field-error \{[^}]*\}/)?.[0] ?? "";
  assert.match(rule, /text-transform: none;/);
  assert.match(rule, /letter-spacing: normal;/);
});

test("the Setup, Runs and Freshness tabs have no heading with the raw key and no extra indent", () => {
  for (const file of ["workspaceKnowledge/sources/SourceSetupDetails.tsx", "workspaceKnowledge/KnowledgeConnectorRun.tsx",
    "workspaceKnowledge/KnowledgeConnectorFreshness.tsx"]) {
    const source = read(file);
    assert.doesNotMatch(source, /user-edit-panel__section/, file);
    assert.doesNotMatch(source, /(Setup|Last run|Freshness) of \{/, file);
  }
});
